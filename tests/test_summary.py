'''Behavior contracts for the hierarchical-summary machinery in context.py:
section parsing/building and the keyword classification driving selective
section updates (ROADMAP Phase 1.2). Deliberately does NOT test candidate
scoring (cosine/ROUGE) — ROADMAP Phase 1.3 replaces it with BERTScore.
'''
import scenarios
from context import (
    QUEST_RESOLUTION_KEYWORDS,
    SECTION_HEADERS,
    STATUS_CHANGE_KEYWORDS,
    _build_summary,
    _classify_exchange,
    _contains_keyword,
    _parse_requested_sections,
    _parse_sections,
)

WELL_FORMED = (
    'OVERALL STORY: Escape the cursed valley.\n\n'
    'CURRENT QUEST: Cross the rope bridge before nightfall.\n\n'
    'PLAYER STATUS: Unharmed, carrying a lantern and 3 gold pieces.'
)


class TestParseSections:
    def test_well_formed(self):
        sections = _parse_sections(WELL_FORMED)
        assert sections == {
            'OVERALL STORY': 'Escape the cursed valley.',
            'CURRENT QUEST': 'Cross the rope bridge before nightfall.',
            'PLAYER STATUS': 'Unharmed, carrying a lantern and 3 gold pieces.',
        }

    def test_round_trip_with_build_summary(self):
        sections = _parse_sections(WELL_FORMED)
        assert _build_summary(sections) == WELL_FORMED

    def test_default_scenario_summary_parses(self):
        # The shipped default summary must always satisfy the parser.
        sections = _parse_sections(scenarios.DEFAULT_SCENARIO['summary'])
        assert sections is not None
        assert set(sections) == set(SECTION_HEADERS)

    def test_case_insensitive_headers(self):
        text = WELL_FORMED.replace('OVERALL STORY', 'Overall Story')
        sections = _parse_sections(text)
        assert sections is not None
        assert sections['OVERALL STORY'] == 'Escape the cursed valley.'

    def test_missing_section_returns_none(self):
        text = ('OVERALL STORY: Escape.\n\n'
                'CURRENT QUEST: Cross the bridge.')
        assert _parse_sections(text) is None

    def test_free_text_returns_none(self):
        assert _parse_sections('The model rambled instead of summarising.') is None

    def test_multi_paragraph_body_preserved(self):
        text = ('OVERALL STORY: First paragraph.\n\nStill the story.\n\n'
                'CURRENT QUEST: Quest.\n\n'
                'PLAYER STATUS: Fine.')
        sections = _parse_sections(text)
        assert 'Still the story.' in sections['OVERALL STORY']

    def test_requested_subset_only(self):
        found = _parse_requested_sections('CURRENT QUEST: Just this one.',
                                          ['CURRENT QUEST'])
        assert found == {'CURRENT QUEST': 'Just this one.'}


class TestContainsKeyword:
    # Prefix matching (leading \b, no trailing boundary) — chosen so stem
    # keywords match their inflected forms. Accepted trade-off: 'heal' also
    # matches "healthy".
    def test_stem_matches_inflected_forms(self):
        assert _contains_keyword('you are badly injured', ['injur'])
        assert _contains_keyword('a healing light surrounds you', ['heal'])
        assert _contains_keyword('you feel exhausted', ['exhaust'])

    def test_no_match_mid_word(self):
        # Leading \b still required: 'hp' must not match inside another word.
        assert not _contains_keyword('the graphps render', ['hp'])

    def test_multi_word_phrase(self):
        assert _contains_keyword('the quest complete fanfare plays',
                                 ['quest complete'])
        assert _contains_keyword('quest completed!', ['quest complete'])
        assert not _contains_keyword('the quest continues', ['quest complete'])

    def test_accepted_tradeoff_prefix_overmatch(self):
        # Documents the deliberate recall-over-precision choice.
        assert _contains_keyword('you feel healthy', ['heal'])


class TestClassifyExchange:
    def test_quest_resolution_touches_quest_and_story(self):
        affected = _classify_exchange('I open the chest',
                                      'Quest complete! The village is saved.')
        assert affected == {'CURRENT QUEST', 'OVERALL STORY'}

    def test_status_change_touches_player_status(self):
        affected = _classify_exchange('I charge the goblin',
                                      'It strikes back; you take 5 damage.')
        assert affected == {'PLAYER STATUS'}

    def test_both_kinds_touch_all_sections(self):
        affected = _classify_exchange(
            'I finish him off',
            'You defeated the warlord but are gravely injured.')
        assert affected == set(SECTION_HEADERS)

    def test_neutral_narration_touches_nothing(self):
        affected = _classify_exchange('I look around',
                                      'The corridor stretches into darkness.')
        assert affected == set()

    def test_keyword_lists_are_lowercase(self):
        # _classify_exchange lowercases the text, so keywords must be
        # lowercase to ever match.
        for keyword in QUEST_RESOLUTION_KEYWORDS + STATUS_CHANGE_KEYWORDS:
            assert keyword == keyword.lower()
