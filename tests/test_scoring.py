'''Behavior contracts for the BERTScore composite candidate scoring in
scoring.py (ROADMAP Phase 1.3). The BERT model is never loaded and no network
is touched: the metric helpers are monkeypatched so only the deterministic
composite/selection logic is exercised.
'''
import pytest

import scoring


class TestCompositeScores:
    def test_weights(self):
        # 0.6 x BERTScore-F1 + 0.2 x ROUGE-L + 0.2 x cosine
        assert scoring.composite_scores([1.0], [0.0], [0.0]) == [pytest.approx(0.6)]
        assert scoring.composite_scores([0.0], [1.0], [0.0]) == [pytest.approx(0.2)]
        assert scoring.composite_scores([0.0], [0.0], [1.0]) == [pytest.approx(0.2)]

    def test_weights_sum_to_one(self):
        assert (scoring.BERT_WEIGHT + scoring.ROUGE_WEIGHT + scoring.COSINE_WEIGHT
                == pytest.approx(1.0))

    def test_parallel_lists(self):
        scores = scoring.composite_scores([0.5, 1.0], [0.5, 0.0], [0.5, 0.0])
        assert scores == [pytest.approx(0.5), pytest.approx(0.6)]

    def test_semantic_outweighs_lexical(self):
        # The point of 1.3: a candidate winning clearly on semantics must beat
        # one that only wins on both lexical signals.
        scores = scoring.composite_scores([0.9, 0.3], [0.2, 1.0], [0.2, 1.0])
        assert scores[0] > scores[1]


class TestSelectBestCandidate:
    def test_picks_composite_argmax(self, monkeypatch):
        monkeypatch.setattr(scoring, '_bert_f1_scores', lambda c, r: [0.1, 0.9, 0.5])
        monkeypatch.setattr(scoring, '_rouge_l_scores', lambda c, r: [0.5, 0.5, 0.5])
        monkeypatch.setattr(scoring, '_cosine_scores', lambda c, r: [0.5, 0.5, 0.5])
        assert scoring.select_best_candidate(['a', 'b', 'c'], 'ref') == 1

    def test_lexical_signals_break_semantic_ties(self, monkeypatch):
        monkeypatch.setattr(scoring, '_bert_f1_scores', lambda c, r: [0.5, 0.5])
        monkeypatch.setattr(scoring, '_rouge_l_scores', lambda c, r: [0.1, 0.9])
        monkeypatch.setattr(scoring, '_cosine_scores', lambda c, r: [0.1, 0.2])
        assert scoring.select_best_candidate(['a', 'b'], 'ref') == 1

    def test_bert_model_not_loaded_when_helper_stubbed(self, monkeypatch):
        # Guards the lazy-loading contract: nothing in the selection logic may
        # touch the scorer singleton except _bert_f1_scores itself.
        monkeypatch.setattr(scoring, '_get_bert_scorer',
                            lambda: pytest.fail('BERT scorer must load lazily'))
        monkeypatch.setattr(scoring, '_bert_f1_scores', lambda c, r: [1.0])
        monkeypatch.setattr(scoring, '_rouge_l_scores', lambda c, r: [1.0])
        monkeypatch.setattr(scoring, '_cosine_scores', lambda c, r: [1.0])
        assert scoring.select_best_candidate(['a'], 'ref') == 0
