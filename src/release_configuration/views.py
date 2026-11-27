from drf_yasg.utils import swagger_auto_schema
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response
from staticfiles import SUPPORTED_MEASURES

from organizations.mixins import UserScopedMixin
from release_configuration.models import ReleaseConfiguration
from release_configuration.serializers import (
    AHPGroupCalculateRequestSerializer,
    AHPGroupCalculateResponseSerializer,
    AHPScaleResponseSerializer,
    DefaultPreConfigSerializer,
    ReleaseConfigurationSerializer,
    calculate_and_serialize_ahp_group,
    serialize_ahp_scale,
)
from utils import staticfiles


class CurrentReleaseConfigModelViewSet(
    UserScopedMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = ReleaseConfiguration.objects.all()
    serializer_class = ReleaseConfigurationSerializer

    @swagger_auto_schema(responses={200: ReleaseConfigurationSerializer})
    def list(self, request, *args, **kwargs):
        # first() == mais recente == pre configuração atual
        product = self.get_product()
        latest_pre_config = product.release_configuration.first()
        serializer = ReleaseConfigurationSerializer(latest_pre_config)
        return Response(serializer.data, status.HTTP_200_OK)


class DefaultPreConfigModelViewSet(
    UserScopedMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = ReleaseConfiguration.objects.all()
    serializer_class = ReleaseConfigurationSerializer

    @swagger_auto_schema(responses={200: DefaultPreConfigSerializer})
    def list(self, request, *args, **kwargs):
        pre_config = staticfiles.DEFAULT_PRE_CONFIG
        serializer = DefaultPreConfigSerializer(pre_config)
        return Response(serializer.data, status.HTTP_200_OK)


class CreateReleaseConfigModelViewSet(
    UserScopedMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ReleaseConfigurationSerializer
    queryset = ReleaseConfiguration.objects.all()

    def perform_create(self, serializer):
        product = self.get_product()
        user = self.request.user if self.request.user and self.request.user.is_authenticated else None
        serializer.save(product=product, created_by=user)

    def create(self, request, *args, **kwargs):
        data_to_add_metrics = request.data

        for characteristic in data_to_add_metrics["data"]["characteristics"]:
            for subcharacteristic in characteristic["subcharacteristics"]:
                for measure in subcharacteristic["measures"]:
                    metrics_list = [
                        sup_measure[measure["key"]]["metrics"]
                        for sup_measure in SUPPORTED_MEASURES
                        if measure["key"] in sup_measure
                    ]
                    measure.update({"metrics": [{"key": metric} for metrics in metrics_list for metric in metrics]})

        serializer = self.get_serializer(data=data_to_add_metrics)
        serializer.is_valid(raise_exception=True)
        product = self.get_product()
        current_release_configuration = product.release_configuration.first()
        if not data_to_add_metrics.get("comparisons") and data_to_add_metrics == current_release_configuration.data:
            return Response(data_to_add_metrics, status=status.HTTP_200_OK)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class AHPScaleViewSet(
    UserScopedMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = ReleaseConfiguration.objects.all()
    serializer_class = AHPScaleResponseSerializer

    @swagger_auto_schema(responses={200: AHPScaleResponseSerializer})
    def list(self, request, *args, **kwargs):
        self.get_product()
        serializer = AHPScaleResponseSerializer(serialize_ahp_scale())
        return Response(serializer.data, status.HTTP_200_OK)


class AHPGroupCalculateViewSet(
    UserScopedMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = ReleaseConfiguration.objects.all()
    serializer_class = AHPGroupCalculateRequestSerializer

    @swagger_auto_schema(
        request_body=AHPGroupCalculateRequestSerializer,
        responses={200: AHPGroupCalculateResponseSerializer},
    )
    def create(self, request, *args, **kwargs):
        self.get_product()
        request_serializer = self.get_serializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        result = calculate_and_serialize_ahp_group(
            request_serializer.validated_data["entities"],
            request_serializer.validated_data["answers"],
        )
        response_serializer = AHPGroupCalculateResponseSerializer(result)
        return Response(response_serializer.data, status=status.HTTP_200_OK)
