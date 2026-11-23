"""
Limpeza dos dados de demonstração que o load_initial_data gravou em produtos e organizações reais antes do
fga-eps-mds/2026.2-MeasureSoftGram-Service#77 (BUG05.04, DOC#151).

Por padrão só lista o que encontrou; com --apply, remove. Remove só o que tem marcação segura:

- metas e releases criadas pelo usuário da carga (SEED_GITHUB_USERNAME, padrão msgramteste) em produtos fora das
  organizações de demonstração. Meta usada por release de outro usuário não é removida (a release iria junto), só
  listada;
- o usuário da carga como membro de organizações reais.

O histórico falso de métricas em repositórios reais não tem marcação e por isso só é listado, para quem conhece os
dados decidir. O comando também avisa se ainda existe o superusuário admin com a senha admin.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from goals.models import Goal
from organizations.management.commands.load_initial_data import Command as LoadInitialData
from organizations.models import Organization, Repository
from releases.models import Release


class Command(BaseCommand):
    help = "Lista (ou remove, com --apply) os dados de demonstração gravados em produtos reais (BUG05.04)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Remove o que foi listado (sem isso, só lista).")

    def handle(self, *args, **options):
        apply = options["apply"]
        demo_organizations = LoadInitialData().demo_organizations()
        real_organizations = Organization.objects.exclude(id__in=demo_organizations)
        seed_user = (
            get_user_model().objects.filter(username=os.getenv("SEED_GITHUB_USERNAME", "msgramteste")).first()
        )

        if seed_user:
            self.clean_seed_data(seed_user, real_organizations, apply)
        else:
            self.stdout.write("Usuário da carga não encontrado: não há metas, releases nem membros da carga.")

        self.report_metric_history(real_organizations)
        self.check_default_admin()
        if not apply:
            self.stdout.write(self.style.WARNING("Nada foi removido (rode com --apply para remover)."))

    def clean_seed_data(self, seed_user, real_organizations, apply):
        releases = Release.objects.filter(created_by=seed_user, product__organization__in=real_organizations)
        goals = Goal.objects.filter(created_by=seed_user, product__organization__in=real_organizations)
        # a release de um usuário real que usa a meta da carga seria apagada em cascata com ela
        kept_goals = goals.filter(release__in=Release.objects.exclude(created_by=seed_user)).distinct()
        goals_to_delete = goals.exclude(id__in=kept_goals)
        memberships = real_organizations.filter(members=seed_user)

        self.stdout.write(f"Releases da carga em produtos reais: {releases.count()}")
        for release in releases:
            self.stdout.write(f"  - {release.product} / {release.release_name}")
        self.stdout.write(f"Metas da carga em produtos reais: {goals_to_delete.count()}")
        for goal in goals_to_delete:
            self.stdout.write(f"  - {goal.product} / meta {goal.id}")
        if kept_goals.exists():
            self.stdout.write(f"Metas da carga mantidas por estarem em releases de usuários: {kept_goals.count()}")
            for goal in kept_goals:
                self.stdout.write(f"  - {goal.product} / meta {goal.id}")
        self.stdout.write(f"Organizações reais com o usuário da carga como membro: {memberships.count()}")
        for organization in memberships:
            self.stdout.write(f"  - {organization.name}")

        if apply:
            with transaction.atomic():
                releases.delete()
                goals_to_delete.delete()
                for organization in memberships:
                    organization.members.remove(seed_user)
            self.stdout.write(self.style.SUCCESS("Releases, metas e participações da carga removidas."))

    def report_metric_history(self, real_organizations):
        repositories = Repository.objects.filter(
            product__organization__in=real_organizations, calculated_tsqmis__isnull=False
        ).distinct()
        self.stdout.write(
            "Repositórios reais com histórico de TSQMI (podem ter dados falsos anteriores ao #77): "
            f"{repositories.count()}"
        )
        for repository in repositories:
            history = repository.calculated_tsqmis.order_by("created_at")
            first, last = history.first(), history.last()
            self.stdout.write(
                f"  - {repository.product} / {repository.name}: {history.count()} valores, "
                f"de {first.created_at:%d/%m/%Y} a {last.created_at:%d/%m/%Y}"
            )

    def check_default_admin(self):
        admin = get_user_model().objects.filter(username="admin").first()
        if admin and admin.check_password("admin"):
            self.stdout.write(
                self.style.ERROR("O usuário admin ainda tem a senha admin: troque a senha ou remova o usuário.")
            )
