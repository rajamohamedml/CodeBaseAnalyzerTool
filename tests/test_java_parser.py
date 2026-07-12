"""Tests for java_parser.py -- purely offline, using embedded Java source
strings rather than a cloned repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from intellisource_ai.exceptions import JavaParseError
from intellisource_ai.java_parser import parse_java_file, parse_source_tree
from intellisource_ai.schemas import ClassType

from .conftest import SAMPLE_BROKEN_JAVA, SAMPLE_CONTROLLER_JAVA, SAMPLE_NESTED_DTO_JAVA


def _write(tmp_path: Path, relative: str, content: str) -> Path:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_parses_controller_with_rest_endpoint(tmp_path: Path) -> None:
    repo_root = tmp_path
    file_path = _write(
        repo_root,
        "src/main/java/com/example/app/services/catalog/controller/ActorController.java",
        SAMPLE_CONTROLLER_JAVA,
    )

    classes = parse_java_file(file_path, repo_root)

    assert len(classes) == 1
    cls = classes[0]
    assert cls.class_name == "ActorController"
    assert cls.class_type == ClassType.CONTROLLER
    assert cls.javadoc == "Exposes read endpoints for actors."
    assert len(cls.methods) == 1

    method = cls.methods[0]
    assert method.name == "getActor"
    assert method.javadoc == "Look up one actor by id."
    assert method.signature == "ActorDto getActor(Integer id)"

    assert len(cls.rest_endpoints) == 1
    endpoint = cls.rest_endpoints[0]
    assert endpoint.http_method == "GET"
    assert endpoint.path == "/actors/{id}"


def test_parses_nested_static_classes(tmp_path: Path) -> None:
    repo_root = tmp_path
    file_path = _write(
        repo_root,
        "src/main/java/com/example/app/services/catalog/domain/dto/ActorDto.java",
        SAMPLE_NESTED_DTO_JAVA,
    )

    classes = parse_java_file(file_path, repo_root)

    class_names = {cls.class_name for cls in classes}
    assert class_names == {"ActorDto", "Actor", "ActorRequest"}

    dto_classes = {cls.class_name: cls for cls in classes}
    assert dto_classes["Actor"].class_type == ClassType.DTO
    assert dto_classes["ActorRequest"].class_type == ClassType.DTO
    assert dto_classes["Actor"].methods[0].name == "getActorId"


def test_broken_file_recorded_as_parse_error_not_raised(tmp_path: Path) -> None:
    repo_root = tmp_path
    _write(repo_root, "src/main/java/Broken.java", SAMPLE_BROKEN_JAVA)
    _write(
        repo_root,
        "src/main/java/com/example/app/services/catalog/controller/ActorController.java",
        SAMPLE_CONTROLLER_JAVA,
    )

    result = parse_source_tree(repo_root)

    assert len(result.parse_errors) == 1
    assert "Broken.java" in result.parse_errors[0]
    assert any(cls.class_name == "ActorController" for cls in result.classes)
    assert result.files_discovered == 2


def test_test_sources_excluded_by_default(tmp_path: Path) -> None:
    repo_root = tmp_path
    _write(
        repo_root,
        "src/main/java/com/example/app/services/catalog/controller/ActorController.java",
        SAMPLE_CONTROLLER_JAVA,
    )
    _write(
        repo_root,
        "src/test/java/com/example/app/services/catalog/controller/ActorControllerTest.java",
        SAMPLE_CONTROLLER_JAVA,
    )

    result_default = parse_source_tree(repo_root, include_tests=False)
    result_with_tests = parse_source_tree(repo_root, include_tests=True)

    assert result_default.files_discovered == 1
    assert result_with_tests.files_discovered == 2


_SAMPLE_ARROW_SWITCH_JAVA = """package com.example.app;

public class ShapeSerializer {

    public void serialize(Shape shape) {
        switch (shape.kind()) {
            case CIRCLE -> drawCircle(shape);
            case SQUARE, RECTANGLE -> drawQuad(shape);
            default -> {
                logUnknown(shape);
                drawFallback(shape);
            }
        }
    }

    public int score(Shape shape) {
        return shape.sides();
    }
}
"""


def test_arrow_style_switch_is_recovered_and_parsed(tmp_path: Path) -> None:
    repo_root = tmp_path
    file_path = _write(
        repo_root, "src/main/java/com/example/app/ShapeSerializer.java", _SAMPLE_ARROW_SWITCH_JAVA
    )

    classes = parse_java_file(file_path, repo_root)

    assert len(classes) == 1
    method_names = {m.name for m in classes[0].methods}
    assert method_names == {"serialize", "score"}
    # Recovery must not shift line numbers: `score` starts well after the
    # switch block, and should land on its real line in the original file.
    score_method = next(m for m in classes[0].methods if m.name == "score")
    assert score_method.start_line == 16


def test_arrow_switch_recovery_does_not_mask_unrelated_errors(tmp_path: Path) -> None:
    repo_root = tmp_path
    file_path = _write(repo_root, "src/main/java/Broken.java", SAMPLE_BROKEN_JAVA)

    with pytest.raises(JavaParseError):
        parse_java_file(file_path, repo_root)
