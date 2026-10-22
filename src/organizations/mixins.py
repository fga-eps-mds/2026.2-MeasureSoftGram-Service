from django.db.models import Q
from django.http import Http404
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import SAFE_METHODS

from organizations.access import find_repository, has_repository_access
from organizations.models import Organization, Product, Repository


class UserScopedMixin:
    """
    Mixin to enforce that querysets and objects are restricted to organizations
    where request.user is a member.

    Em leitura, quem tem acesso a um repositório no provedor (`RepositoryAccess`) também enxerga
    esse repositório, o produto e a organização dele. Escrita exige ser membro.
    """

    def _read_only_request(self):
        return self.request.method in SAFE_METHODS

    def get_user_organizations(self):
        user = self.request.user
        if not self._read_only_request():
            return Organization.objects.filter(members=user)
        return Organization.objects.filter(
            Q(members=user) | Q(products__repositories__accesses__user=user)
        ).distinct()

    def get_user_products(self):
        user = self.request.user
        if not self._read_only_request():
            return Product.objects.filter(organization__members=user)
        return Product.objects.filter(
            Q(organization__members=user) | Q(repositories__accesses__user=user)
        ).distinct()

    def get_user_repositories(self):
        user = self.request.user
        if not self._read_only_request():
            return Repository.objects.filter(product__organization__members=user)
        return Repository.objects.filter(
            Q(product__organization__members=user) | Q(accesses__user=user)
        ).distinct()

    def get_organization(self):
        org_pk = self.kwargs.get("organization_pk") or self.kwargs.get("pk")
        return get_object_or_404(self.get_user_organizations(), id=org_pk)

    def get_product(self):
        org_pk = self.kwargs.get("organization_pk")
        prod_pk = self.kwargs.get("product_pk") or self.kwargs.get("pk")
        return get_object_or_404(self.get_user_products().filter(organization_id=org_pk), id=prod_pk)

    def get_repository(self):
        org_pk = self.kwargs.get("organization_pk")
        prod_pk = self.kwargs.get("product_pk")
        repo_pk = self.kwargs.get("repository_pk") or self.kwargs.get("pk")
        member_repositories = Repository.objects.filter(
            product__organization__members=self.request.user,
            product_id=prod_pk,
            product__organization_id=org_pk,
        )
        member_repository = member_repositories.filter(id=repo_pk).first()
        if member_repository:
            return member_repository

        # Não é membro: só leitura, e só se o provedor ainda libera o repositório.
        repository = find_repository(org_pk, prod_pk, repo_pk)
        if repository is None:
            raise Http404
        if not self._read_only_request():
            raise PermissionDenied("Acesso somente leitura a este repositório.")
        if not has_repository_access(self.request.user, repository):
            raise Http404
        return repository
