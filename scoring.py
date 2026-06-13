import os

# On Windows without Developer Mode the huggingface_hub cache cannot use
# symlinks and falls back to copying; the cache still works, so silence the
# one-time warning. Must be set before huggingface_hub is first imported
# (lazily, in _get_bert_scorer).
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')

from rouge_score import rouge_scorer
from sklearn.metrics.pairwise import cosine_similarity
import spacy

nlp = spacy.load('en_core_web_md')

# BERTScore base model (ROADMAP 1.3). MIT-licensed; ~1.4 GB one-time download
# on first use. The deberta-mnli models ranked higher by bert-score ship only
# .bin weights, which transformers 5.x refuses to torch.load on this venv's
# torch 2.5.1 (CVE-2025-32434 guard) — the model here must provide
# safetensors. BERTScorer picks CUDA automatically when available.
BERTSCORE_MODEL = 'roberta-large'

# Composite weights: semantic quality dominates, the lexical signals are kept
# as a guard against candidates that drift from the reference wording.
BERT_WEIGHT = 0.6
ROUGE_WEIGHT = 0.2
COSINE_WEIGHT = 0.2

_rouge = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=True)
_bert_scorer = None

def _get_bert_scorer():
    '''
    Lazy singleton: importing bert_score pulls in torch/transformers and the
    first instantiation downloads the model, so defer both until the first
    actual scoring call.
    '''
    global _bert_scorer
    if _bert_scorer is None:
        # Silence transformers' weight-loading progress bar and LOAD REPORT.
        # The reported key mismatches are expected: the checkpoint is an MLM
        # model (extra lm_head.*) while BERTScore uses the bare encoder and
        # never touches the freshly-initialised pooler.* weights.
        from transformers.utils import logging as hf_logging
        hf_logging.set_verbosity_error()
        hf_logging.disable_progress_bar()
        # huggingface_hub has its own logger tree the transformers setting
        # does not cover; it relays server-sent X-HF-Warning headers (e.g.
        # "You are sending unauthenticated requests to the HF Hub") when the
        # model is checked against the Hub.
        from huggingface_hub.utils import logging as hub_logging
        hub_logging.set_verbosity_error()
        from bert_score import BERTScorer
        _bert_scorer = BERTScorer(model_type=BERTSCORE_MODEL)
    return _bert_scorer

def _bert_f1_scores(candidate_texts, reference):
    _, _, f1 = _get_bert_scorer().score(
        candidate_texts,
        [reference] * len(candidate_texts)
    )
    return [float(score) for score in f1]

def _rouge_l_scores(candidate_texts, reference):
    return [
        _rouge.score(text, reference)['rougeL'].fmeasure
        for text in candidate_texts
    ]

def _cosine_scores(candidate_texts, reference):
    reference_doc = nlp(reference)
    return [
        cosine_similarity([reference_doc.vector], [nlp(text).vector])[0][0]
        for text in candidate_texts
    ]

def composite_scores(bert_f1s, rouge_ls, cos_sims):
    '''
    Weighted composite per ROADMAP 1.3:
    0.6 x BERTScore-F1 + 0.2 x ROUGE-L + 0.2 x cosine.
    Inputs are parallel lists, one entry per candidate.
    '''
    return [
        BERT_WEIGHT * bert_f1s[i]
        + ROUGE_WEIGHT * rouge_ls[i]
        + COSINE_WEIGHT * cos_sims[i]
        for i in range(len(bert_f1s))
    ]

def _fallback_scores(rouge_ls, cos_sims) -> list:
    '''
    Composite used when BERTScore is unavailable (import, download or runtime
    failure) so the session can continue on the lexical signals alone.
    Inputs are parallel lists, one entry per candidate; returns a list of
    scores of the same length.
    '''
    return [0.5 * rouge + 0.5 * cos_sim for rouge, cos_sim in zip(rouge_ls, cos_sims)]

def select_best_candidate(candidate_texts, reference):
    '''
    Return the index of the candidate scoring highest against the reference.
    '''
    rouge_ls = _rouge_l_scores(candidate_texts, reference)
    cos_sims = _cosine_scores(candidate_texts, reference)

    try:
        bert_f1s = _bert_f1_scores(candidate_texts, reference)
        scores = composite_scores(bert_f1s, rouge_ls, cos_sims)
    except Exception as e:
        print(f"WARNING: BERTScore unavailable ({e}); falling back to lexical-only scoring.")
        scores = _fallback_scores(rouge_ls, cos_sims)

    return scores.index(max(scores))
