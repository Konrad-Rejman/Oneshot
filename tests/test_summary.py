'''
Behavior contracts for the hierarchical-summary machinery in context.py:
section parsing/building and the keyword classification driving selective
section updates (ROADMAP Phase 1.2). Candidate scoring lives in scoring.py
and is covered by test_scoring.py.
'''
import scenarios
from context import (
    QUEST_RESOLUTION_KEYWORDS,
    SECTION_HEADERS,
    STATUS_CHANGE_KEYWORDS,
    SUMMARY_UPDATE_INTERVAL,
    _affected_sections,
    _apply_forced_update,
    _build_summary,
    _classify_exchange,
    _contains_keyword,
    _parse_partial_sections,
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

    def test_markdown_decorated_headers(self):
        # The summariser model decorates headings despite being told not to;
        # the parser must tolerate bold/underscore/heading markers.
        text = ('**OVERALL STORY**: Escape the cursed valley.\n\n'
                '## CURRENT QUEST: Cross the rope bridge before nightfall.\n\n'
                '__PLAYER STATUS__: Unharmed, carrying a lantern and 3 gold pieces.')
        assert _parse_sections(text) == _parse_sections(WELL_FORMED)

    def test_bold_header_colon_inside(self):
        # "**CURRENT QUEST:** text" puts the colon inside the bold markers,
        # leaving "**" at the start of the body - must be stripped.
        found = _parse_requested_sections('**CURRENT QUEST:** Cross the bridge.',
                                          ['CURRENT QUEST'])
        assert found == {'CURRENT QUEST': 'Cross the bridge.'}

    def test_empty_body_treated_as_missing(self):
        # A bare heading must never blank out a section.
        assert _parse_requested_sections('CURRENT QUEST:', ['CURRENT QUEST']) is None


class TestParsePartialSections:
    def test_salvages_present_subset(self):
        found = _parse_partial_sections('CURRENT QUEST: Updated quest.',
                                        ['OVERALL STORY', 'CURRENT QUEST'])
        assert found == {'CURRENT QUEST': 'Updated quest.'}

    def test_none_when_no_requested_section_present(self):
        assert _parse_partial_sections('The model rambled instead.',
                                       ['CURRENT QUEST']) is None

    def test_full_coverage_matches_strict_parser(self):
        assert (_parse_partial_sections(WELL_FORMED, SECTION_HEADERS)
                == _parse_requested_sections(WELL_FORMED, SECTION_HEADERS))


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


class TestApplyForcedUpdate:
    # Staleness guard: a full refresh is forced once SUMMARY_UPDATE_INTERVAL
    # turns (counting the current one) pass without a successful update.
    def test_keyword_sections_pass_through_untouched(self):
        assert _apply_forced_update(['PLAYER STATUS'], 99) == ['PLAYER STATUS']

    def test_no_force_before_interval(self):
        assert _apply_forced_update([], SUMMARY_UPDATE_INTERVAL - 1) == []

    def test_forces_full_refresh_at_interval(self):
        assert _apply_forced_update([], SUMMARY_UPDATE_INTERVAL) == list(SECTION_HEADERS)

    def test_stays_due_past_interval(self):
        # A failed forced refresh retries the very next turn rather than
        # waiting another full interval.
        assert _apply_forced_update([], SUMMARY_UPDATE_INTERVAL + 3) == list(SECTION_HEADERS)


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


class TestAffectedSections:
    # _classify_exchange plus the ROADMAP 2.3 STATE-line signal: a turn whose
    # STATE line reported a mechanical change always touches PLAYER STATUS,
    # even when the (state-line-stripped) narration dodges the keyword lists.
    def test_state_change_forces_player_status(self):
        affected = _affected_sections('I duck behind the crates',
                                      'The bolt grazes you as you dive.', True)
        assert affected == {'PLAYER STATUS'}

    def test_no_state_change_matches_plain_classification(self):
        action, response = 'I look around', 'The corridor stretches into darkness.'
        assert (_affected_sections(action, response, False)
                == _classify_exchange(action, response) == set())

    def test_state_change_adds_to_keyword_sections(self):
        affected = _affected_sections('I finish him off',
                                      'You defeated the warlord.', True)
        assert affected == set(SECTION_HEADERS)
