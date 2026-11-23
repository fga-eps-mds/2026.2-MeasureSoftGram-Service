import os
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TransactionTestCase
from django.utils import timezone

from goals.models import Goal
from organizations.management.commands.load_initial_data import Command as LoadInitialData
from organizations.models import Organization, Product, Repository
from releases.models import Release


class LimparSeedDemoTestCase(TransactionTestCase):
    """
    O limpar_seed_demo (BUG05.04, DOC#151) remove o que a carga antiga gravou num produto real e não toca no resto:
    o produto, os dados do usuário real e as organizações de demonstração.
    """

    SEED_USERNAME = os.getenv("SEED_GITHUB_USERNAME", "msgramteste")

    def setUp(self):
        self.load = LoadInitialData()
        self.load.create_supported_metrics()
        self.load.create_suported_measures()
        self.load.create_github_suported_measures()
        self.load.create_supported_subcharacteristics()
        self.load.create_supported_characteristics()

        self.user = get_user_model().objects.create_user(username="usuaria-real", password="senha-de-teste")
        self.org = Organization.objects.create(name="Org Real", admin=self.user)
        self.org.members.add(self.user)
        self.product = Product.objects.create(name="Produto Real", organization=self.org)
        self.repository = Repository.objects.create(name="repo-real", product=self.product)

        # o que a carga antiga fazia no produto real: meta, duas releases e o usuário da carga como membro
        self.load.create_a_goal(self.product)
        self.load.create_a_release(self.product)
        self.seed_user = get_user_model().objects.get(username=self.SEED_USERNAME)
        self.org.members.add(self.seed_user)

    def run_command(self, *args):
        out = StringIO()
        call_command("limpar_seed_demo", *args, stdout=out)
        return out.getvalue()

    def test_sem_apply_so_lista(self):
        output = self.run_command()

        self.assertIn("Releases da carga em produtos reais: 2", output)
        self.assertIn("Metas da carga em produtos reais: 1", output)
        self.assertIn("Org Real", output)
        self.assertIn("Nada foi removido", output)
        self.assertEqual(Release.objects.filter(product=self.product).count(), 2)
        self.assertTrue(self.org.members.filter(username=self.SEED_USERNAME).exists())

    def test_com_apply_remove_so_o_que_a_carga_gravou(self):
        self.run_command("--apply")

        self.assertFalse(Release.objects.filter(product=self.product).exists())
        self.assertFalse(Goal.objects.filter(product=self.product).exists())
        self.assertFalse(self.org.members.filter(username=self.SEED_USERNAME).exists())
        self.assertTrue(self.org.members.filter(username="usuaria-real").exists())
        self.assertTrue(Product.objects.filter(id=self.product.id).exists())
        self.assertTrue(Repository.objects.filter(id=self.repository.id).exists())

    def test_meta_usada_por_release_de_usuario_real_fica(self):
        goal = Goal.objects.get(product=self.product)
        Release.objects.create(
            release_name="Release da usuária",
            start_at=timezone.now(),
            end_at=timezone.now(),
            created_by=self.user,
            product=self.product,
            goal=goal,
        )

        output = self.run_command("--apply")

        self.assertIn("Metas da carga mantidas por estarem em releases de usuários: 1", output)
        self.assertTrue(Goal.objects.filter(id=goal.id).exists())
        remaining = Release.objects.filter(product=self.product).values_list("created_by", flat=True)
        self.assertEqual(list(remaining), [self.user.id])

    def test_nao_toca_nas_organizacoes_de_demonstracao(self):
        call_command("load_initial_data", fake_data=True)
        demo_releases = Release.objects.exclude(product=self.product).count()
        self.assertGreater(demo_releases, 0)

        self.run_command("--apply")

        self.assertEqual(Release.objects.exclude(product=self.product).count(), demo_releases)

    def test_avisa_do_admin_com_senha_padrao(self):
        get_user_model().objects.create_superuser(username="admin", email="", password="admin")

        self.assertIn("ainda tem a senha admin", self.run_command())
