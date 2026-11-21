from core.ahp import CR_THRESHOLD, SAATY_PHRASES, SAATY_SCALE, calculate_group, most_inconsistent
from drf_yasg.utils import swagger_serializer_method
from rest_framework import serializers

from release_configuration.models import ReleaseConfiguration
from utils.exceptions import InvalidReleaseConfigurationException


class ReleaseConfigurationSerializer(serializers.ModelSerializer):
    created_config = serializers.SerializerMethodField("has_created_config")

    class Meta:
        model = ReleaseConfiguration
        fields = ("id", "name", "data", "created_at", "created_config")
        extra_kwargs = {
            "created_at": {"read_only": True},
            "created_config": {
                "read_only": True,
            },
        }

    @swagger_serializer_method(serializers.BooleanField())
    def has_created_config(self, obj):
        return len(ReleaseConfiguration.objects.values("id")) > 1

    def validate(self, attrs):
        """
        Valida se a pré-configuração que está sendo criada é válida
        """
        if self.instance:
            raise ValueError("It's not allowed to edit a release-configuration")

        data = attrs["data"]

        try:
            ReleaseConfiguration.validate_measures(data)
            ReleaseConfiguration.validate_measures_weights(data)
            ReleaseConfiguration.validate_subcharacteristics(data)
            ReleaseConfiguration.validate_subcharacteristics_measures_relation(data)
            ReleaseConfiguration.validate_subcharacteristics_weights(data)
            ReleaseConfiguration.validate_characteristics(data)
            ReleaseConfiguration.validate_characteristics_subcharacteristics_relation(data)
            ReleaseConfiguration.validate_characteristics_weights(data)

        except InvalidReleaseConfigurationException as exc:
            raise serializers.ValidationError(exc) from exc

        return attrs


class MeasureSerializer(serializers.Serializer):
    key = serializers.CharField()
    weight = serializers.IntegerField()
    min_threshold = serializers.IntegerField()
    max_threshold = serializers.IntegerField()


class SubCharacteristicSerializer(serializers.Serializer):
    key = serializers.CharField()
    weight = serializers.IntegerField()
    measures = serializers.ListField(child=MeasureSerializer())


class CharacteristicSerializer(serializers.Serializer):
    key = serializers.CharField()
    weight = serializers.IntegerField()
    subcharacteristics = serializers.ListField(child=SubCharacteristicSerializer())


class DefaultPreConfigSerializer(serializers.Serializer):
    characteristics = serializers.ListField(child=CharacteristicSerializer())


class AHPAnswerSerializer(serializers.Serializer):
    a = serializers.CharField()
    b = serializers.CharField()
    preferred = serializers.CharField(allow_null=True, required=False, default=None)
    intensity = serializers.CharField()


class AHPConflictSerializer(serializers.Serializer):
    a = serializers.CharField()
    b = serializers.CharField()
    answer = AHPAnswerSerializer()
    suggested = AHPAnswerSerializer()
    suggested_ratio = serializers.FloatField()


class AHPGroupCalculateRequestSerializer(serializers.Serializer):
    entities = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False,
    )
    answers = AHPAnswerSerializer(many=True)


class AHPGroupCalculateResponseSerializer(serializers.Serializer):
    priorities = serializers.DictField(child=serializers.FloatField())
    weights = serializers.DictField(child=serializers.IntegerField())
    consistency_ratio = serializers.FloatField(allow_null=True)
    consistent = serializers.BooleanField()
    cr_threshold = serializers.FloatField()
    conflict = AHPConflictSerializer(allow_null=True)


class AHPScaleResponseSerializer(serializers.Serializer):
    scale = serializers.DictField(child=serializers.IntegerField())
    phrases = serializers.DictField(child=serializers.CharField())
    cr_threshold = serializers.FloatField()


def _answer_tuple_to_dict(answer_tuple):
    a, b, preferred, intensity = answer_tuple
    return {
        "a": a,
        "b": b,
        "preferred": preferred,
        "intensity": intensity,
    }


def serialize_ahp_scale():
    return {
        "scale": dict(SAATY_SCALE),
        "phrases": dict(SAATY_PHRASES),
        "cr_threshold": CR_THRESHOLD,
    }


def calculate_and_serialize_ahp_group(entities, answers):
    answer_tuples = [
        (item["a"], item["b"], item.get("preferred"), item["intensity"])
        for item in answers
    ]
    try:
        result = calculate_group(entities, answer_tuples)
        conflict = most_inconsistent(entities, answer_tuples, result)
    except ValueError as exc:
        raise serializers.ValidationError({"detail": str(exc)}) from exc

    return {
        "priorities": result.priorities,
        "weights": result.weights,
        "consistency_ratio": result.consistency_ratio,
        "consistent": result.consistent,
        "cr_threshold": CR_THRESHOLD,
        "conflict": (
            {
                "a": conflict.a,
                "b": conflict.b,
                "answer": _answer_tuple_to_dict(conflict.answer),
                "suggested": _answer_tuple_to_dict(conflict.suggested),
                "suggested_ratio": conflict.suggested_ratio,
            }
            if conflict is not None
            else None
        ),
    }
