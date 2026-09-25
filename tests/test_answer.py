from types import SimpleNamespace

import pytest

from sifthound.answer import AnswerError, AnswerGenerator
from sifthound.config import Settings
from sifthound.models import SearchResult


def _generator(exc: Exception) -> AnswerGenerator:
    async def create(**kwargs):
        raise exc

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    return AnswerGenerator(Settings(), client=client)


RESULTS = [SearchResult(title="t", url="https://a.test/", content="c", score=1.0)]


async def test_missing_credentials_is_answer_error():
    gen = _generator(TypeError('"Could not resolve authentication method. Expected one of ..."'))
    with pytest.raises(AnswerError, match="no Anthropic credentials"):
        await gen.generate("q", RESULTS, "basic")


async def test_unrelated_type_error_propagates():
    gen = _generator(TypeError("unexpected keyword argument"))
    with pytest.raises(TypeError):
        await gen.generate("q", RESULTS, "basic")
