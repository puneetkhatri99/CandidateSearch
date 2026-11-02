import json

from app.features.semantic_search.service import JudgementCounter


def _answer(count: int) -> str:
    judgements = [{"candidate": n, "skills_score": 70, "skills_note": "x"} for n in range(count)]
    return json.dumps({"search_names_place": False, "judgements": judgements})


def test_counts_each_judgement_once_however_the_text_arrives() -> None:
    text = _answer(25)
    for piece in (1, 7, 40, len(text)):
        counter = JudgementCounter()
        seen = [counter.update(text[:end]) for end in range(piece, len(text) + piece, piece)]
        assert seen[-1] == 25, piece
        assert seen == sorted(seen)  # never goes backwards


def test_a_key_split_across_two_pieces_is_counted_once() -> None:
    counter = JudgementCounter()
    text = '{"judgements": [{"candidate": 1}, {"candidate": 2}]}'
    split = text.index('"candidate": 2') + 5  # inside the second key

    assert counter.update(text[:split]) == 1
    assert counter.update(text) == 2
    assert counter.update(text) == 2
