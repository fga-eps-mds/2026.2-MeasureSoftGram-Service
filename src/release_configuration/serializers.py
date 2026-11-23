from core.ahp import CR_THRESHOLD, SAATY_PHRASES, SAATY_SCALE, calculate_group, most_inconsistent
from django.db import transaction
from drf_yasg.utils import swagger_serializer_method
from rest_framework import serializers

from release_configuration.models import ReleaseConfiguration, ReleaseConfigurationComparison
from utils.exceptions import InvalidReleaseConfigurationException


class AHPAnswerSerializer(serializers.Serializer):
    a = serializers.CharField()
    b = serializers.CharField()
    preferred = serializers.CharField(allow_null=True, required=False, default=None)
    intensity = serializers.CharField()


class AHPGroupComparisonInputSerializer(serializers.Serializer):
    group_path = serializers.CharField()
    entities = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False,
    )
    answers = AHPAnswerSerializer(many=True)
    accepted_inconsistent = serializers.BooleanField(required=False, default=False)


class ReleaseConfigurationSerializer(serializers.ModelSerializer):
    created_config = serializers.SerializerMethodField("has_created_config")
    comparisons = AHPGroupComparisonInputSerializer(many=True, required=False, write_only=True)

    class Meta:
        model = ReleaseConfiguration
        fields = ("id", "name", "data", "created_at", "created_config", "comparisons")
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

        if "comparisons" in attrs and attrs["comparisons"] is not None:
            attrs["comparisons"] = validate_and_build_ahp_comparisons(data, attrs["comparisons"])

        return attrs

    def create(self, validated_data):
        comparisons = validated_data.pop("comparisons", None)
        created_by = validated_data.pop("created_by", None)
        if created_by is None:
            request = self.context.get("request")
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                created_by = user

        with transaction.atomic():
            release_config = super().create(validated_data)
            if comparisons:
                ReleaseConfigurationComparison.objects.create(
                    release_configuration=release_config,
                    created_by=created_by,
                    groups=comparisons,
                )
        return release_config


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


def _resolve_group_items(data, group_path):
    parts = [part for part in group_path.strip("/").split("/") if part]
    characteristics = data.get("characteristics", [])

    if parts == ["characteristics"]:
        return characteristics

    if len(parts) == 2 and parts[1] == "subcharacteristics":
        char_key = parts[0]
        for char in characteristics:
            if char.get("key") == char_key:
                return char.get("subcharacteristics", [])
        raise serializers.ValidationError({"comparisons": f"Unknown characteristic in group_path: `{group_path}`."})

    if len(parts) == 3 and parts[2] == "measures":
        char_key, subchar_key, _ = parts
        for char in characteristics:
            if char.get("key") == char_key:
                for subchar in char.get("subcharacteristics", []):
                    if subchar.get("key") == subchar_key:
                        return subchar.get("measures", [])
        raise serializers.ValidationError(
            {"comparisons": f"Unknown subcharacteristic in group_path: `{group_path}`."}
        )

    raise serializers.ValidationError({"comparisons": f"Invalid group_path: `{group_path}`."})


def validate_and_build_ahp_comparisons(data, comparisons):
    seen_paths = set()
    validated_groups = []

    for group in comparisons:
        group_path = group["group_path"].strip("/")
        if group_path in seen_paths:
            raise serializers.ValidationError({"comparisons": f"Duplicate group_path: `{group_path}`."})
        seen_paths.add(group_path)

        group_items = _resolve_group_items(data, group_path)
        expected_entities = [item["key"] for item in group_items]
        entities = group["entities"]

        if entities != expected_entities:
            raise serializers.ValidationError(
                {
                    "comparisons": (
                        f"Entities for group `{group_path}` do not match configuration order: "
                        f"expected {expected_entities}, got {entities}."
                    )
                }
            )

        calc = calculate_and_serialize_ahp_group(entities, group["answers"])
        accepted_inconsistent = bool(group.get("accepted_inconsistent", False))

        if not calc["consistent"] and not accepted_inconsistent:
            raise serializers.ValidationError(
                {
                    "comparisons": (
                        f"Group `{group_path}` has consistency_ratio {calc['consistency_ratio']:.4f} "
                        f"above {CR_THRESHOLD} and was not explicitly accepted."
                    )
                }
            )

        actual_weights = {item["key"]: item["weight"] for item in group_items}
        if actual_weights != calc["weights"]:
            raise serializers.ValidationError(
                {
                    "comparisons": (
                        f"Weights in data for group `{group_path}` ({actual_weights}) "
                        f"do not match calculated AHP weights ({calc['weights']})."
                    )
                }
            )

        validated_groups.append(
            {
                "group_path": group_path,
                "entities": entities,
                "answers": [
                    {
                        "a": ans["a"],
                        "b": ans["b"],
                        "preferred": ans.get("preferred"),
                        "intensity": ans["intensity"],
                    }
                    for ans in group["answers"]
                ],
                "priorities": calc["priorities"],
                "weights": calc["weights"],
                "consistency_ratio": calc["consistency_ratio"],
                "consistent": calc["consistent"],
                "accepted_inconsistent": bool(accepted_inconsistent and not calc["consistent"]),
            }
        )

    return validated_groups
