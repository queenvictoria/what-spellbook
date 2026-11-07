"""Rules lookup against the vendored 2024 SRD.

This module had no tests at all while it fetched from a website, and the rewrite from
scraping to local files showed what that cost: a two-character query word ("dc") was being
dropped, a prefix match let "long rest" answer itself from "Restrained", the file holding
the best match lost to the file with the most text, and two of the matcher's own helper
functions disagreed about what a stem was. Every one of those was invisible from the
outside - a rules answer that is subtly wrong reads exactly like one that is right.

So these tests fall into two groups:

* **Properties** - the fold and its inverse agree; tables keep their numbers; a question
  the SRD cannot answer is refused rather than answered with something adjacent.
* **Regression cases** - the specific questions that were answered wrongly, kept as named
  cases so the reason survives the next rewrite of the matcher.

The assertions are on *which heading* answered a question, not on the wording of a passage.
That is the stable contract: the passage is the SRD's text and will change with the SRD,
but the heading that answers "what is a short rest" should not.
"""

from __future__ import annotations

import pytest

from backend.libs import config, rules


# --- the vendored corpus is present and complete -------------------------------


def test_the_vendored_srd_is_present():
    """A missing corpus must be a clear failure, not a lookup that finds nothing."""
    files = rules.source_files()
    assert files, f"no SRD files found at {rules.srd_dir()}"
    names = {path.name for path in files}
    assert "rules-glossary.md" in names
    assert "playing-the-game.md" in names


def test_attribution_is_not_searched_as_rules_text():
    """PROVENANCE.md is the CC-BY-4.0 notice, not SRD text.

    It is deliberately excluded: licence boilerplate contains words like "work",
    "material" and "rights", and including it would let it answer a question.
    """
    assert "PROVENANCE.md" not in {path.name for path in rules.source_files()}


def test_preferred_files_come_first():
    files = [path.name for path in rules.source_files()]
    assert files[: len(rules.PREFERRED_FILES)] == list(rules.PREFERRED_FILES)


# --- edition guard -------------------------------------------------------------


@pytest.mark.parametrize("url", ["https://5thsrd.org/x.html", "http://www.5thsrd.org/y"])
def test_a_2014_source_is_refused(url):
    """The project is 2024-only, so a 2014 host must fail loudly rather than be used."""
    with pytest.raises(rules.RulesUnavailable, match="2014"):
        rules.check_source(url)


def test_the_superseded_website_is_refused():
    """5e24srd.com is 2024 but omits the Rules Glossary, so it cannot answer rests."""
    with pytest.raises(rules.RulesUnavailable, match="omits"):
        rules.check_source("https://5e24srd.com/playing-the-game/index.html")


def test_a_local_srd_file_is_permitted():
    rules.check_source(rules.srd_dir() / "rules-glossary.md")


# --- folding: the fold and its inverse must stay in step -----------------------


@pytest.mark.parametrize(
    "word",
    ["conditions", "grappling", "grappled", "stabilize", "stabilizing", "hiding", "hides",
     "cover", "covers", "spells", "rolls", "rolling"],
)
def test_folding_a_word_matches_its_own_pattern(word):
    """``_fold`` decides the term and ``_term_pattern`` finds it again.

    These two have to agree. When they did not, "stabilize" folded to one stem and
    "stabilizing" to another, so a question and the heading that answered it disagreed
    about whether they were the same word, and the lookup missed.
    """
    folded = rules._fold(word)
    assert rules._term_pattern(folded).search(word), f"{word!r} -> {folded!r} does not match"


@pytest.mark.parametrize(
    "verb,noun",
    [
        ("concentrate", "Concentration"),
        ("attune", "Attunement"),
        ("react", "Reaction"),
        ("act", "Action"),
        ("move", "Movement"),
        ("equip", "Equipment"),
    ],
)
def test_a_verb_folds_to_the_noun_the_rulebook_names_the_rule_with(verb, noun):
    """A question asks with the verb; the rulebook names the rule with the noun.

    "how do I concentrate on a spell" folded to ``concentrat`` while the glossary's own
    heading "Concentration" folded to ``concentration``, so the two never met and the SRD's
    full definition of Concentration could not be found by asking for it. The same gap hid
    Attunement, Reaction, Action, Movement and Equipment behind their verbs.
    """
    assert rules._fold(verb) == rules._fold(noun.lower())
    assert rules._term_pattern(rules._fold(verb)).search(noun.lower())


@pytest.mark.parametrize(
    "word,other",
    [("rest", "Restrained"), ("rest", "Restoration"), ("cover", "coverage"),
     ("hit", "hitherto"), ("hide", "hideous"), ("moment", "momentum")],
)
def test_a_stem_does_not_match_a_longer_unrelated_word(word, other):
    """A prefix match is not a match.

    ``\\brest`` matches "Restrained" and "Restoration", which is how "what is a long rest"
    was answered from the Restrained condition: its heading merely *starts* with the same
    letters.
    """
    assert not rules._term_pattern(rules._fold(word)).search(other.lower())


def test_short_acronyms_survive_term_extraction():
    """"dc", "ac" and "hp" are the rulebook's short words and must not be dropped.

    Dropping anything under three characters left "what is my spell save dc" matching a
    shop entry called "Spell Scroll" on "spell" and "save" alone - two of two remaining
    terms, so every gate passed and the answer was simply wrong.
    """
    assert "dc" in rules._terms("what is my spell save dc")
    assert "ac" in rules._terms("what is my ac")


def test_question_framing_words_are_not_terms():
    """Filler names the question, not the rule, so it must not weight a match."""
    terms = rules._terms("what are the rules for jumping")
    assert terms == {"jump"}


@pytest.mark.parametrize(
    "question,subject",
    [
        ("explain the initiative system to me like I'm 12yo", "initiativ"),
        ("explain advantage", "advantag"),
        ("tell me about opportunity attacks", "opportunity"),
        ("define difficult terrain", "difficult"),
        ("elaborate on exhaustion", "exhaust"),
        ("walk me through a short rest", "short"),
        ("I want to understand spell slots", "slot"),
        ("help me understand attunement", "attun"),
    ],
)
def test_an_asking_verb_does_not_outrank_the_subject(question, subject):
    """A framing verb is rare in a rulebook, so rarity alone elects it as the subject.

    This is the failure the stopword list exists to prevent, and it is worse than a bad
    ranking: :func:`_qualifies` requires a heading naming the subject, no heading contains
    "explain", and so a question the SRD answers perfectly well was reported as absent.
    The rarer the verb the harder it fails - "elaborate" weighs 0.98 against "exhaustion"
    at 0.93, so the question was refused on the strength of its own phrasing.

    The expected subject is the *folded* stem, because that is what a term is: "exhaustion"
    folds to ``exhaust`` and "attunement" to ``attun``, and :func:`_term_pattern` reaches
    the heading back from there.
    """
    terms = rules._terms(question)
    weights = {term: rules.term_weight(term) for term in terms}
    assert max(weights, key=lambda term: weights[term]) == subject


@pytest.mark.parametrize(
    "word",
    ["help", "describe", "list", "find", "learn", "read", "see"],
)
def test_a_framing_word_that_names_a_rule_is_kept(word):
    """Some asking words are also rules, and dropping them breaks working questions.

    "Help [Action]" is a heading, so "how does the help action work" must keep "help" as a
    term. The same is true of "describe", "list", "find", "learn", "read" and "see". Only
    words that name no heading at all may be dropped, which is why the list is enumerated
    rather than guessed at.

    Compared on the folded form, because that is what :func:`_terms` returns - "describe"
    arrives as ``describ``.
    """
    assert rules._fold(word) in rules._terms(f"how does the {word} action work")


@pytest.mark.parametrize(
    "question,heading",
    [
        ("explain the initiative system to me like I'm 12yo", "Initiative"),
        ("explain advantage", "Advantage"),
        ("tell me about opportunity attacks", "Opportunity Attacks"),
        ("define difficult terrain", "Difficult Terrain"),
        ("elaborate on exhaustion", "Exhaustion"),
        ("walk me through a short rest", "Short Rest"),
        ("help me understand attunement", "Attunement"),
        ("can you explain concentration", "Concentration"),
    ],
)
def test_a_conversationally_phrased_question_reaches_its_rule(question, heading):
    """The same rule, however the question is asked.

    A player asking "explain the initiative system to me like I'm 12yo" wants the Initiative
    rule, not a report that the SRD has no section by that name. The phrasing is the
    question's, not the rule's, so it must not decide the answer.
    """
    result = rules.gather(question)
    headings = [
        line.removeprefix("## ")
        for line in result["passages"][0].splitlines()
        if line.startswith("## ")
    ]
    assert any(heading.lower() in h.lower() for h in headings), \
        f"{question!r} answered from {headings!r}"


# --- markdown conversion -------------------------------------------------------


def test_headings_become_sentinels():
    """A rule is defined under its own heading, so headings must survive conversion."""
    text = rules.markdown_to_text("## Combat\n\nSome prose.\n\n#### Cover\n\nMore prose.")
    assert "## Combat" in text
    assert "## Cover" in text


def test_table_values_are_kept_as_readable_text():
    """The rules are in the tables, so the numbers must not be stripped away.

    The SRD's prose only says "as detailed in the Cover table". Dropping the markup would
    leave a confident answer with the +2 and +5 bonuses missing, which is worse than no
    answer at all.
    """
    table = (
        "**Cover**\n\n"
        "<table><thead><tr><th>Degree</th><th>Benefit</th></tr></thead><tbody>"
        "<tr><td>Half</td><td>+2 bonus to AC</td></tr></tbody></table>"
    )
    text = rules.markdown_to_text(table)
    assert "+2 bonus to AC" in text
    assert "Half" in text
    # Both the column header and the row survive, so a passage reads on its own.
    assert "Degree: Half" in text
    assert "Benefit: +2 bonus to AC" in text


def test_a_table_caption_does_not_split_its_section():
    """"**Cover**" above a table inside "### Cover" must not become a second heading.

    Promoting it split one rule across two sections, so the retrieval limit could return
    the explanation without the table the explanation refers to.
    """
    markdown = (
        "### Cover\n\nAs detailed in the Cover table...\n\n"
        "**Cover**\n\n<table><tbody><tr><td>Half</td><td>+2 AC</td></tr></tbody></table>"
    )
    headings = [h for h, _body, _parent in rules._sections(rules.markdown_to_text(markdown))]
    assert headings.count("Cover") == 1


def test_run_in_labels_become_sections():
    """A rule defined as a labelled case within a section must become reachable.

    "Shove" is defined only as "_Shove._ The target must succeed..." inside "Unarmed
    Strike", so without promoting the label there is no heading to match.
    """
    markdown = (
        "#### Unarmed Strike\n\n"
        "_Shove._ The target must succeed on a Strength saving throw.\n\n"
        "_Grapple._ The target must succeed on a Strength saving throw."
    )
    sections = rules._sections(rules.markdown_to_text(markdown))
    headings = [h for h, _body, _parent in sections]
    assert "Shove" in headings
    assert "Grapple" in headings


def test_a_run_in_label_is_recorded_as_a_part_of_its_rule():
    """Each promoted label points at the rule its heading introduced.

    This link is what lets retrieval return a rule whole. It has to be a real heading:
    the label is promoted to a *distinct* marker level so the parent is never another
    label, which would have grouped unrelated rules under whichever part happened to be
    their nearest neighbour.
    """
    markdown = (
        "#### Grappling\n\nA creature can grapple another creature.\n\n"
        "_Ending a Grapple._ A Grappled creature can use its action to escape.\n\n"
        "_Rolling the Die._ A d20 is rolled."
    )
    sections = rules._sections(rules.markdown_to_text(markdown))
    headings = [h for h, _body, _parent in sections]
    grappling = headings.index("Grappling")
    parent_of = {heading: parent for heading, _body, parent in sections}
    assert parent_of["Grappling"] == -1
    assert parent_of["Ending a Grapple"] == grappling
    assert parent_of["Rolling the Die"] == grappling


def test_a_part_stays_a_part_across_a_nested_case():
    """A label under a label attaches to the same rule, not to its sibling.

    Conditions define their effects as labels, and effects are labels too, so the parent
    link must survive two levels of promotion - otherwise "Speed 0" would be grouped with
    "Grappled [Condition]" only when it happened to be listed first.
    """
    markdown = (
        "#### Prone [Condition]\n\nWhile Prone, you experience these effects.\n\n"
        "_Speed 0._ Your Speed is 0.\n\n"
        "_Attacks Affected._ You have Disadvantage.\n\n"
        "#### Unrelated\n\nA different rule entirely."
    )
    sections = rules._sections(rules.markdown_to_text(markdown))
    headings = [h for h, _body, _parent in sections]
    prone = headings.index("Prone [Condition]")
    parent_of = {heading: parent for heading, _body, parent in sections}
    assert parent_of["Speed 0"] == prone
    assert parent_of["Attacks Affected"] == prone
    assert parent_of["Unrelated"] == -1


def test_a_bolded_sentence_opening_is_not_promoted():
    """Only a label ending in a full stop is a run-in label.

    Without the full stop requirement any sentence opening in bold becomes a heading, so a
    paragraph is split into a bogus heading and a fragment.
    """
    markdown = "#### X\n\n**Note** this is prose that merely starts boldly."
    sections = rules._sections(rules.markdown_to_text(markdown))
    headings = [h for h, _body, _parent in sections]
    assert "X" in headings
    assert not any(heading.startswith("Note") for heading in headings)
    # A promoted label that was skipped must not leave a parent behind for a section that
    # was never created.
    assert all(parent in (-1, *range(len(sections))) for _h, _b, parent in sections)


# --- term weighting ------------------------------------------------------------


def test_a_word_the_book_uses_everywhere_carries_little_signal():
    """Frequency over the text, not over headings.

    "creature" is rare in *headings* and everywhere in the *sections*, so measuring rarity
    against headings alone rated it nearly as distinctive as "stabilizing" - and
    "how do I stabilize a creature" was answered with the glossary's definition of a
    creature, because the generic object of the question looked like its subject.
    """
    assert rules.term_weight("creatur") < rules.term_weight("stabiliz")
    assert rules.term_weight("creatur") < rules.term_weight("shov")


def test_a_word_absent_from_the_srd_weighs_nothing():
    """Absence must be worth zero, or "not found" turns into "found".

    Weighting an unmatched term as maximally *rare* would make "how does a spear work"
    look like an excellent match, when the honest answer is that the SRD has no rules for
    spears.
    """
    assert rules.term_weight("zzzznottaword") == 0.0


# --- answering ----------------------------------------------------------------


@pytest.mark.parametrize(
    "question,heading",
    [
        ("what is a short rest", "Short Rest"),
        ("what is a long rest", "Long Rest"),
        ("how does cover work", "Cover"),
        ("what is half cover", "Cover"),
        ("how does grappling work", "Grappled"),
        ("how do I shove a creature", "Shove"),
        ("how do I stabilize a creature", "Stabilizing"),
        ("how do death saving throws work", "Death Saving Throw"),
        ("what does blinded do", "Blinded"),
        ("what is the poisoned condition", "Poisoned"),
        ("how does concentration work", "Concentration"),
        ("what is a bonus action", "Bonus Action"),
        ("how do opportunity attacks work", "Opportunity Attacks"),
        ("what is a hit point", "Hit Point"),
        ("how does difficult terrain work", "Difficult Terrain"),
        # A question carrying context alongside its subject: the heading names only the
        # subject, because "combat" is where the question was asked, not what it asks.
        ("can I hide in combat", "Hid"),
    ],
)
def test_a_rule_question_is_answered_from_the_heading_that_names_it(question, heading):
    """The heading is the contract: the passage is the SRD's text and will change.

    The passage is the top-ranked *rule*, which may be several sections rendered together,
    so the heading is looked up among them rather than only in the first line. "how does
    grappling work" returns the whole Grappling rule, whose parts include the heading
    named here.
    """
    result = rules.gather(question)
    headings = [
        line.removeprefix("## ")
        for line in result["passages"][0].splitlines()
        if line.startswith("## ")
    ]
    assert any(heading.lower() in h.lower() for h in headings), \
        f"{question!r} answered from {headings!r}"


@pytest.mark.parametrize(
    "question",
    [
        "how does two weapon fighting work",
        "how does flanking work",
        "how does a spear work",
    ],
)
def test_a_rule_the_srd_does_not_contain_is_refused(question):
    """Refusing is the honest outcome, and a plausible paragraph is worse than saying so.

    Two-weapon fighting and flanking are 2024 rules the SRD does not carry. Both used to be
    answered anyway, from "Roll Two D20s" and from "Combat" respectively, because a heading
    merely shared a word with the question. Rarity is what fixes it: those headings matched
    on "two" and "combat", words the rulebook uses everywhere, so they cannot identify a
    rule.

    "how does a spear work" is the same failure arriving from the other direction. The
    Spear is a weapon that lives inside an equipment *table* with no heading of its own, so
    once the class chapter was vendored the only heading containing the word was "Eldritch
    Spear" - a Warlock invocation, and not what was asked about. A leading qualifier the
    question never mentioned is what rules it out.

    This is a boundary rather than a guarantee. A question whose subject the SRD does not
    have but which shares a distinctive word with a neighbouring rule can still return that
    neighbour - "what is a subclass feature" reaches "Special Feature". That is deliberate:
    the retrieved passage is offered as the best candidate, and ``rules_prompt`` requires
    the model to say plainly when it does not answer the question rather than filling the
    gap from memory.
    """
    with pytest.raises(rules.RulesUnavailable):
        rules.gather(question)


@pytest.mark.parametrize(
    ("question", "heading"),
    [
        # Both were refused before the class chapter was vendored, and both are genuinely
        # in it. Multiclassing is a rule the SRD carries; the wizard's spellbook is a class
        # feature. Refusing them was the gap, not the guard.
        ("how do I multiclass", "Multiclass"),
        ("what is a wizard's spellbook", "Spellbook"),
    ],
)
def test_a_class_rule_is_answered_from_the_class_chapter(question, heading):
    """Vendoring classes.md must widen what can be answered, not just add invocations."""
    result = rules.gather(question)
    assert result["url"].split("#")[0] == "context/srd/classes.md"
    assert heading.lower() in result["passages"][0].splitlines()[0].lower()


# --- the inferred path ---------------------------------------------------------


def test_an_inferred_answer_is_still_anchored_to_a_heading():
    """The fallback relaxes the subject floor, and nothing else.

    "what is a spell attack" is answered by the glossary's own "Spell Attack" heading, but
    the question's most distinctive term is the generic "attack", which the precise path's
    subject floor rejects. Lowering that floor is the whole of the fallback: the heading
    anchor and the qualifier gate stay, because they are what stop the failures below.
    """
    result = rules.gather_inferred("what is a spell attack")
    headings = [
        line.removeprefix("## ")
        for line in result["passages"][0].splitlines()
        if line.startswith("## ")
    ]
    assert any("spell attack" in h.lower() for h in headings), headings


@pytest.mark.parametrize(
    "question",
    [
        # No heading names it, and the SRD has no two-weapon rule at all. Without the
        # heading anchor this is answered from "The Order of Combat", which is a plausible
        # paragraph about a different thing.
        "how does two weapon fighting work",
        # The Spear lives inside an equipment table with no heading, so the only heading
        # containing the word is "Eldritch Spear" - a Warlock invocation. The qualifier
        # gate is what rejects it.
        "how does a spear work",
        # The SRD carries no general flanking rule.
        "how does flanking work",
    ],
)
def test_the_inferred_path_refuses_what_the_precise_path_refuses(question):
    """A fallback that answers everything is not a fallback, it is a guess with a citation.

    Each of these was a real false positive while the fallback was being built, and each
    came back when one of the two remaining gates was loosened.
    """
    with pytest.raises(rules.RulesUnavailable):
        rules.gather_inferred(question)


def test_the_inferred_path_reports_a_missing_corpus():
    """It must not answer from nothing when the vendored SRD is absent."""
    with pytest.raises(rules.RulesUnavailable, match="No SRD text found"):
        rules.gather_inferred("what is a spell attack", files=[])


def test_an_inferred_answer_records_how_it_was_reached(tmp_path):
    """A cache hit skips retrieval, so the distinction has to be *stored*.

    Recomputing it on read is not possible - the retrieval that decided it does not run -
    and an interpreted answer served as a quotation is the exact failure the source label
    exists to prevent.
    """
    rules.save_cached("what is a spell attack", "Roll d20 and add your spell attack bonus.",
                      passages=["## Spell Attack"], url="context/srd/rules-glossary.md",
                      answer_source="rules-inferred", cache_dir=tmp_path)
    entry = rules.load_cached("what is a spell attack", tmp_path)
    assert entry is not None
    assert entry["answer_source"] == "rules-inferred"


def test_a_quoted_answer_defaults_to_the_quoted_label(tmp_path):
    """The precise path is the common case, so it must not need to say so."""
    rules.save_cached("what is a short rest", "One hour of downtime.", passages=[],
                      url="context/srd/rules-glossary.md", cache_dir=tmp_path)
    entry = rules.load_cached("what is a short rest", tmp_path)
    assert entry is not None
    assert entry["answer_source"] == "rules"


def test_a_leading_qualifier_is_not_mistaken_for_the_subject():
    """A heading that *qualifies* the subject is naming a different thing.

    "Eldritch Spear" is a Warlock invocation; the question was about a spear. English puts
    the head noun last, so only the words before the first match are qualifiers - which is
    what keeps "Grappled Condition" (correct for "how does grappling work") while rejecting
    "Eldritch Spear".
    """
    assert rules._qualifier_weight("Eldritch Spear", {"spear"}) > 0.5
    assert rules._qualifier_weight("Grappled Condition", {"grappl"}) == 0.0
    assert rules._qualifier_weight("Stabilizing a Character", {"stabiliz"}) == 0.0
    # The class chapter prefixes every feature heading with its level, which says nothing
    # about the subject and must not count as a qualifier.
    assert rules._qualifier_weight("Level 2: Wild Shape", {"wild", "shap"}) == 0.0


def test_a_missing_corpus_is_reported_not_answered():
    """With no files at all the message must say so, rather than claiming no such rule."""
    with pytest.raises(rules.RulesUnavailable, match="No SRD text found"):
        rules.gather("what is a short rest", files=[], cache_dir="/tmp")


def test_the_citation_is_a_repo_relative_file():
    """A URL would look clickable and lead nowhere: the source is a local file now."""
    citation = rules.gather("what is a short rest")["url"]
    assert citation.startswith("context/srd/")
    assert citation.split("#")[0].endswith(".md")


def test_the_citation_is_anchored_to_the_section_that_answered():
    """The path is what the UI prints and what the drawer opens.

    A bare file is a poor link: `playing-the-game.md` is 65KB and `classes.md` 296KB, so
    opening one at the top leaves the reader to find the rule themselves. The anchor is
    derived from the vendored text rather than stored, so it cannot go stale against a
    heading that was renamed.
    """
    citation = rules.gather("what is a short rest")["url"]
    assert citation == "context/srd/rules-glossary.md#short-rest"


def test_a_citation_falls_back_to_the_file_when_the_heading_has_no_anchor():
    """A promoted run-in label ("Ending a Grapple") is not a heading in the file.

    It has no anchor, and the file is the honest answer for it - better than a link to a
    section that does not exist.
    """
    citation = rules.gather("how does grappling work")["url"]
    assert citation.startswith("context/srd/")
    assert "#" not in citation or citation.split("#")[1]


def test_the_best_match_wins_over_the_longest_passage():
    """The file is chosen on match quality, not on how much text it holds.

    An earlier version compared by passage length, so "what is a long rest" was answered
    from an equipment entry titled "Attune during a Short Rest" purely because that passage
    was longer than the glossary's own definition of a long rest.
    """
    result = rules.gather("what is a long rest")
    assert "long rest" in result["passages"][0].splitlines()[0].lower()


def test_a_matched_rule_comes_back_with_its_later_parts():
    """A rule's parts are retrieved together, not ranked against each other.

    The SRD defines "Grappling" as a lead sentence followed by run-in parts, and the part
    that says how to *end* a grapple repeats the word far less than the opening does. Ranked
    independently, the opening three parts filled the passage limit and the escape rules
    were cut - so "how does grappling work" returned a definition of grappling that stopped
    before saying what to do about one. Silently: nothing in the passage said it was partial.
    """
    text = rules.gather("how does grappling work")["passages"][0]
    assert "Ending a Grapple" in text
    assert "escape DC" in text


def test_a_condition_comes_back_with_all_of_its_effects():
    """"Grappled [Condition]" defines its effects as run-in parts, including "Speed 0".

    The effects are the whole of the entry, so returning "While you have the Grappled
    condition, you experience the following effects." on its own promises effects and
    supplies none.
    """
    passages = rules.gather("how does grappling work")["passages"]
    condition = next(p for p in passages if p.startswith("## Grappled [Condition]"))
    for effect in ("Speed 0", "Attacks Affected", "Movable"):
        assert effect in condition


def test_a_part_is_not_folded_into_a_heading_that_is_off_topic():
    """Its own heading wins when the heading above it does not answer the question.

    The stat block and the wizard's "Spellcasting" feature both contain dozens of promoted
    parts, and their headings match nothing in the question. Folding on the parent link
    alone returned the entire stat block for "what is a bonus action" and the whole level 1
    feature for "what is a wizard's spellbook" - the answer buried in the middle of it.
    """
    bonus_action = rules.gather("what is a bonus action")["passages"][0]
    assert bonus_action.splitlines()[0] == "## Bonus Actions"

    spellbook = rules.gather("what is a wizard's spellbook")["passages"][0]
    assert spellbook.splitlines()[0] == "## Spellbook"
    assert "Cantrips" not in spellbook


def test_a_part_of_a_rule_is_still_reachable_on_its_own():
    """Grouping must not undo the promotion: "Shove" is a rule in its own right.

    "Shove" is only ever a run-in label under "Unarmed Strike", so folding it back
    unconditionally would leave the question with nothing headed "Shove" to match - the
    exact problem promoting run-in labels solved.
    """
    result = rules.gather("how do I shove a creature")
    assert result["passages"][0].splitlines()[0] == "## Shove"
    assert "Strength or Dexterity saving throw" in result["passages"][0]


# --- caching -------------------------------------------------------------------


def test_a_cached_answer_from_the_old_source_is_not_reused(tmp_path):
    """Answers written against the scraped website must not outlive the fix.

    Several of them report a rule as missing that the vendored SRD defines - because the
    website omitted the Rules Glossary - so serving them from cache would keep the bug
    alive after the bug was fixed.
    """
    import json

    path = rules.entry_path("what is a short rest", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "question": "what is a short rest",
        "answer": "The SRD does not define a Short Rest.",
        "passages": [],
        "url": "https://5e24srd.com/",
        "source": "5e24srd.com",
    }))

    assert rules.load_cached("what is a short rest", tmp_path) is None
    result = rules.gather("what is a short rest", cache_dir=tmp_path)
    assert result["from_cache"] is False


def test_an_answer_from_an_older_retrieval_is_not_reused(tmp_path):
    """Changing *which* passages a question returns must retire its cached answer.

    The source file is untouched and still says ``vendored-srd-5.2.1``, so the source
    check alone cannot see it. An answer written from the older passages would keep being
    served with the *new* passages reported alongside it, which is worse than a stale
    answer on its own: the citation would contradict the text it was meant to support.
    """
    import json

    path = rules.entry_path("how does grappling work", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "question": "how does grappling work",
        "answer": "A grappled creature has Speed 0.",
        "passages": ["## Grappling"],          # the pre-grouping, truncated passages
        "url": "context/srd/rules-glossary.md",
        "source": rules.RULES_SOURCE,
        "retrieval_version": rules.RETRIEVAL_VERSION - 1,
    }))

    assert rules.load_cached("how does grappling work", tmp_path) is None
    assert rules.gather("how does grappling work", cache_dir=tmp_path)["from_cache"] is False


def test_a_conversational_question_retires_its_older_answer(tmp_path):
    """The framing-verb fix changed retrieval, so answers cached before it must not serve.

    A question phrased conversationally used to be *refused*, and a refusal is not cached -
    but the same question could also have been answered from the wrong passage, and either
    way the entry predates the fix. The source file is unchanged, so only the retrieval
    version can retire it.
    """
    import json

    path = rules.entry_path("explain advantage", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "question": "explain advantage",
        "answer": "The 2024 SRD has no section matching 'explain advantage'.",
        "passages": [],
        "url": "context/srd/playing-the-game.md",
        "source": rules.RULES_SOURCE,
        "retrieval_version": 2,
    }))

    assert rules.load_cached("explain advantage", tmp_path) is None
    assert rules.gather("explain advantage", cache_dir=tmp_path)["from_cache"] is False


def test_an_answer_is_cached_under_the_current_source(tmp_path):
    rules.save_cached("what is a short rest", "One hour of downtime.", passages=["## Short Rest"],
                      url="context/srd/rules-glossary.md", cache_dir=tmp_path)
    entry = rules.load_cached("what is a short rest", tmp_path)
    assert entry is not None
    assert entry["source"] == rules.RULES_SOURCE
    assert entry["retrieval_version"] == rules.RETRIEVAL_VERSION
    assert entry["answer"] == "One hour of downtime."


def test_a_cached_answer_still_reports_its_passages(tmp_path):
    """``from_cache`` is about the *answer*, not about skipping retrieval.

    The stored passages are returned with it so a caller can still show what the answer
    was grounded in, without re-reading the files.
    """
    rules.save_cached("how does cover work", "Walls and trees provide cover.",
                      passages=["## Cover\n\nWalls and trees provide cover."],
                      url="context/srd/playing-the-game.md", cache_dir=tmp_path)
    result = rules.gather("how does cover work", cache_dir=tmp_path)
    assert result["from_cache"] is True
    assert result["passages"] == ["## Cover\n\nWalls and trees provide cover."]
    assert "Walls and trees" in result["text"]


def test_rewording_a_question_hits_the_same_cache_entry(tmp_path):
    """"What is a short rest?" and "what is a short rest" are the same question."""
    rules.save_cached("What is a Short Rest?", "One hour of downtime.", passages=[],
                      url="context/srd/rules-glossary.md", cache_dir=tmp_path)
    assert rules.load_cached("what is a short rest", tmp_path) is not None


def test_a_corrupt_cache_entry_is_ignored(tmp_path):
    """A half-written cache file must not break a lookup."""
    path = rules.entry_path("what is a short rest", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json")
    assert rules.load_cached("what is a short rest", tmp_path) is None


# --- the deliverable the class was actually built for --------------------------


def test_a_short_rest_question_now_reaches_the_glossary():
    """The end-to-end reason for vendoring: the website could not answer this at all.

    It published a page pointing at a "Rules Glossary" it did not contain, so the answer
    came back as a travel-pace sentence about mounts. The glossary is vendored here, and
    its definition is what gets returned.
    """
    text = rules.gather("what is a short rest")["text"]
    assert "Short Rest" in text
    assert "1-hour period of downtime" in text


def test_cover_keeps_the_numbers_the_prose_refers_to():
    """The section and the table it points at are returned together."""
    text = rules.gather("how does cover work")["text"]
    assert "Cover" in text
    assert "+2" in text and "+5" in text


# --- spell descriptions ---------------------------------------------------------


def test_spells_are_indexed_from_the_vendored_srd():
    """The spell list is the SRD's, and it is non-trivial.

    Asserted as a range rather than an exact count so reissuing the SRD does not break the
    test, while a parse that silently returns nothing (or returns the casting rules as
    spells) still fails.
    """
    names = rules.spell_names()
    assert 300 < len(names) < 400, f"unexpected spell count: {len(names)}"
    assert "fireball" in names
    assert "eldritch blast" in names


@pytest.mark.parametrize(
    "not_a_spell",
    [
        "Actions",
        "Animated Object",
        "Spell Slots",
        "Using a Higher-Level Spell Slot",
        "Traits",
    ],
)
def test_nested_headings_are_not_indexed_as_spells(not_a_spell):
    """``spells.md`` interleaves machinery among the spells, and it must not be offered.

    "Animated Object", "Actions" and "Traits" are ``####`` headings nested *inside* the
    spells that reference them, and the casting rules use ``####`` too. A spell has a level
    line; nothing else does.
    """
    assert rules.find_spell(not_a_spell) is None


def test_a_spell_returns_its_own_text_verbatim():
    """No model is involved, so the numbers cannot be paraphrased."""
    spell = rules.find_spell("Fireball")
    assert spell is not None
    assert spell["name"] == "Fireball"
    assert "8d6 Fire damage" in spell["text"]
    # Anchored to the spell's own heading: `spells.md` is 325KB of 352 descriptions, so a
    # link to the file alone would open the book at the top.
    assert spell["url"] == "context/srd/spells.md#fireball"
    assert spell["source"] == rules.RULES_SOURCE


def test_a_spell_body_does_not_repeat_the_name():
    """The card renders `name` as its heading, so the body must not open with it.

    Both sources carry the name as their first line. Left in, every spell card printed its
    own title twice.
    """
    for name in ("Fireball", "Thorn Whip"):
        spell = rules.find_spell(name)
        assert spell is not None
        assert not spell["text"].startswith(spell["name"]), name
        assert spell["text"].startswith("_"), name


def test_a_spell_name_keeps_the_srd_spelling():
    """The index is keyed lowercase, but the card shows the name as the SRD writes it."""
    spell = rules.find_spell("fireball")
    assert spell is not None
    assert spell["name"] == "Fireball"


def test_spell_lookup_ignores_case_and_spacing():
    """"fireball" and " Fireball " are the same spell."""
    assert rules.find_spell("fireball") == rules.find_spell(" Fireball ")


@pytest.mark.parametrize("name", ["", "   ", "Not A Real Spell"])
def test_an_unknown_spell_returns_nothing(name):
    """A miss must be falsy so the caller can say the SRD has no such spell."""
    assert rules.find_spell(name) is None


def test_a_spell_name_the_srd_dropped_falls_back_to_the_corpus():
    """The 2024 SRD removed product identity, so the branded name is not in the SRD.

    The corpus carries "Tenser's Floating Disk"; the SRD has "Floating Disk". Returning the
    SRD spell for the branded name would silently present a different spell from the one
    asked for, so the corpus entry is returned instead and `source` says so.
    """
    branded = rules.find_spell("Tenser's Floating Disk")
    assert branded is not None
    assert branded["source"] == rules.CORPUS_SOURCE
    assert branded["name"] == "Tenser's Floating Disk"

    plain = rules.find_spell("Floating Disk")
    assert plain is not None
    assert plain["source"] == rules.RULES_SOURCE


# --- Eldritch Invocations ---


def test_invocations_are_read_from_the_vendored_class_chapter():
    """The invocation options live in the SRD's class chapter, and that is the source.

    They are not in any other vendored file - the chapter is the only place the effect
    text exists - so the section is located by heading within an 11,000-line document.
    """
    names = rules.invocation_names()
    assert len(names) >= 25, f"unexpected invocation count: {len(names)}"
    for name in ("Agonizing Blast", "Repelling Blast", "Eldritch Spear",
                 "Mask of Many Faces", "Pact of the Tome"):
        assert name in names, name

    assert len(rules._invocations_index()) == 28


def test_an_invocation_is_quoted_from_the_srd():
    """The SRD is the authority, and it carries the effect text our context does not.

    Our own class context lists all 28 invocations with their level and prerequisite but
    not what they do, so it can only answer "may I take this?" - the SRD answers "what
    does it do?". The card shows the source, so the distinction has to survive.
    """
    invocation = rules.find_invocation("Agonizing Blast")
    assert invocation is not None
    assert invocation["source"] == rules.RULES_SOURCE
    # Anchored, because `classes.md` is 11,000 lines of class features.
    assert invocation["url"] == "context/srd/classes.md#agonizing-blast"
    assert invocation["name"] == "Agonizing Blast"


def test_an_invocation_carries_its_effect_text():
    """The effect is the point of the card, and it is what the class context lacks.

    Before the class chapter was vendored the card showed only "Minimum Warlock level 2 ·
    Prerequisite: ... · Repeatable" - which answers whether the invocation may be taken,
    not what it does.
    """
    agonizing = rules.find_invocation("Agonizing Blast")
    assert "Charisma modifier" in agonizing["text"]
    assert "Level 2+ Warlock" in agonizing["text"]

    faces = rules.find_invocation("Mask of Many Faces")
    assert "Disguise Self" in faces["text"]

    tome = rules.find_invocation("Pact of the Tome")
    assert "Book of Shadows" in tome["text"]


def test_the_class_context_is_the_fallback_for_an_invocation_the_srd_lacks():
    """Our context still answers when the SRD does not, and says so.

    It carries the level and prerequisite for all 28, so it is a real fallback rather than
    a stub - but it is not the authority, and the response must not claim to be.
    """
    row = rules._invocation_rows()["agonizing blast"]
    assert row["level"] == 2
    assert row["repeatable"] is True
    assert row["url"] == "context/classes/warlock/base.md"

    # The rendered fallback names the level and prereq, and no effect text.
    text = rules._invocation_text(row)
    assert "level 2" in text
    assert "damage-dealing Warlock cantrip" in text
    assert "Repeatable" in text

    # A row with no prereq must not render the literal "-" the table uses for "none".
    faces = rules._invocation_text(rules._invocation_rows()["mask of many faces"])
    assert "Prerequisite" not in faces
    assert "-" not in faces


def test_an_invocation_is_not_a_spell():
    """The two lookups must stay separate.

    Folding invocations into `find_spell` would make a class feature answer as if it were
    an SRD spell, and would let a spell lookup return something that is not a spell.
    """
    assert rules.find_spell("Agonizing Blast") is None
    assert rules.find_invocation("Fireball") is None


def test_every_invocation_name_resolves():
    """A name offered for linking must not 404, checked across the whole list."""
    misses = [n for n in rules.invocation_names() if rules.find_invocation(n) is None]
    assert misses == [], f"{len(misses)} invocation names do not resolve: {misses[:5]}"


def test_a_corpus_only_cantrip_resolves():
    """Thorn Whip is in the corpus and not the SRD, and the app recommends it.

    This is the case that made the corpus fallback necessary: a spell link that 404s for
    the Warlock's own cantrips is worse than no link at all.
    """
    spell = rules.find_spell("Thorn Whip")
    assert spell is not None
    assert spell["source"] == rules.CORPUS_SOURCE
    assert "1d6 Piercing damage" in spell["text"]


def test_a_corpus_spell_is_named_as_its_page_names_it():
    """The page's own title is the authority, not the filename.

    Six corpus files are named after a different spell than the page holds - "Confusion.md"
    contains Conjure Animals - and "Meld Into Stone.md" capitalises a minor word the page
    does not. Keying the corpus index on the filename would file Conjure Animals' text
    under "Confusion", so a lookup for Confusion would return the wrong spell's rules.

    All six misnamed files happen to hold a spell the SRD also has, so the SRD answers
    first and the corpus file is never reached for those names. The filename must still
    not be offered as a corpus name, or the corpus would claim to hold a spell it does not.
    """
    from backend.libs import spells as spells_module

    corpus = spells_module.corpus_spell_names()
    assert "Conjure Animals" in corpus
    # The filename's spelling is not a corpus name, because the page is not that spell.
    assert "Confusion" not in corpus
    assert "Vitriolic Sphere" not in corpus

    # And the SRD still answers for the names the filenames claimed.
    for name in ("Confusion", "Disintegrate", "Flame Blade", "Greater Restoration"):
        spell = rules.find_spell(name)
        assert spell is not None, name
        assert spell["source"] == rules.RULES_SOURCE, name


def test_linkable_names_are_the_union_of_both_sources():
    """The link list must cover both sources, not just the corpus.

    The SRD carries 22 spells the corpus does not - the 2024 generic renames of the 2014
    branded ones - and a model writing 2024 prose may use either name. Offering only the
    corpus's names leaves the 2024 name as dead text.
    """
    names = rules.linkable_spell_names()
    assert len(names) > 500

    # Corpus-only, SRD-only, and the branded/generic pair that differs between them.
    assert "Thorn Whip" in names
    assert "Hideous Laughter" in names
    assert "Tasha's Hideous Laughter" in names
    assert "Floating Disk" in names
    assert "Tenser's Floating Disk" in names


def test_every_linkable_name_resolves():
    """A name offered for linking must not 404.

    This is the whole point of the list: the front end turns a name into a link, and a
    link that opens "not in the SRD" is worse than plain text. Checked across all 539
    names rather than a sample, because a single bad name is invisible in a spot check.
    """
    misses = [n for n in rules.linkable_spell_names() if rules.find_spell(n) is None]
    assert misses == [], f"{len(misses)} linkable names do not resolve: {misses[:5]}"


def test_linkable_names_are_unique_case_and_apostrophe_insensitively():
    """The two sources must not produce the same spell twice under two spellings.

    The corpus writes a typographic apostrophe where the SRD writes a straight one, so
    "Tenser's Floating Disk" would otherwise appear twice and the front end would build a
    pattern with a duplicate alternative.
    """
    names = rules.linkable_spell_names()
    folded = [rules._fold_name(n) for n in names]
    assert len(folded) == len(set(folded))


def test_a_corpus_spell_is_normalised_into_the_srd_shape():
    """The corpus's dialect must not reach the renderer.

    The corpus writes a markdown link title, a line of hashtags, and a non-breaking space
    after each run-in label. Any of those surviving renders as visible markup.
    """
    spell = rules.find_spell("Thorn Whip")
    assert spell is not None
    text = spell["text"]
    assert "dndbeyond.com" not in text
    assert "#" not in text
    assert "\xa0" not in text
    assert text.startswith("_Transmutation Cantrip (Druid)_")
    assert "_Cantrip Upgrade._ The damage increases" in text


def test_every_corpus_spell_normalises_cleanly():
    """The corpus has three title spellings and links rules terms inline.

    133 of its 544 spells write the title as a bare `# Name` rather than a markdown link,
    and 343 link rules terms inline. A normaliser that handles only the common case leaves
    visible markup on a third of the corpus, so this walks all of it.
    """
    paths = rules._corpus_spell_paths()
    assert len(paths) > 500, f"unexpected corpus size: {len(paths)}"
    assert "glamerweave" not in paths, "a magic item was indexed as a spell"

    leftovers = []
    for key in paths:
        spell = rules._corpus_spell(key)
        if spell is None:
            continue
        text = spell["text"]
        for marker in ("](", "[[", "]]", "\xa0", "dndbeyond.com"):
            if marker in text:
                leftovers.append((key, marker))
                break
        else:
            if text.startswith("#"):
                leftovers.append((key, "bare title"))
    assert not leftovers, f"{len(leftovers)} spells kept markup: {leftovers[:5]}"


def test_a_corpus_spell_with_a_bare_title_heading_is_normalised():
    """`# Blade of Disaster` is the other title spelling, and it must be dropped too."""
    spell = rules.find_spell("Blade of Disaster")
    assert spell is not None
    assert spell["source"] == rules.CORPUS_SOURCE
    assert spell["text"].startswith("_Level 9 Conjuration")


def test_a_corpus_spell_keeps_inline_link_text():
    """The corpus links rules terms; the SRD writes them plain, and so must we."""
    spell = rules.find_spell("Bestow Curse")
    assert spell is not None
    assert "Concentration, up to 1 minute" in spell["text"]
    assert "](http" not in spell["text"]


def test_every_srd_spell_renders_without_markup():
    """13 SRD spells carry their table inline as HTML, and the renderer has no table syntax.

    Augury, Confusion, Prismatic Spray and friends would otherwise print `<table>` and
    `<td>` at the reader. The tables are the spell's content - Confusion's whole behaviour
    table is one - so they are rendered as sentences rather than dropped.
    """
    leftovers = []
    for name in rules.spell_names():
        spell = rules.find_spell(name)
        if spell is None:
            continue
        text = spell["text"]
        for marker in ("<", "&amp;", "&#", "](", "[[", "\xa0", ".."):
            if marker in text:
                leftovers.append((name, marker))
                break
    assert not leftovers, f"{len(leftovers)} spells kept markup: {leftovers[:5]}"


def test_an_srd_spell_table_becomes_sentences():
    """The numbers in a table are the spell's content and must survive."""
    spell = rules.find_spell("Augury")
    assert spell is not None
    assert "Omen: Weal; For Results That Will Be: Good." in spell["text"]
    assert "Omen: Indifference" in spell["text"]


def test_a_corpus_spell_unwraps_a_wiki_link():
    """73 spells cross-reference another spell as `[[Wall of Force]]`.

    The markdown-link pattern matches the inner `[Wall of Force]` and leaves the outer
    brackets behind, so the wiki form has to be unwrapped first.
    """
    spell = rules.find_spell("Blade of Disaster")
    assert spell is not None
    assert "including a Wall of Force." in spell["text"]
    assert "[[" not in spell["text"]


def test_a_spell_in_neither_source_is_none():
    """A genuine miss must stay a miss, or the 404 branch becomes unreachable."""
    assert rules.find_spell("Flaming Death Ray") is None


@pytest.mark.parametrize("item", ["Glamerweave", "Armblade", "Docent", "Earworm"])
def test_a_magic_item_is_not_offered_as_a_spell(item):
    """The corpus's `Spells/` directory holds 22 magic items alongside the spells.

    They are told apart by their stats line - a spell names a level or a cantrip, an item
    names a rarity - and offering one as a spell would put a magic item behind a spell
    link.
    """
    assert rules.find_spell(item) is None


# --- the selection path --------------------------------------------------------
#
# The contextual menu takes a phrase copied out of a generated book, which is not a
# question and is not written in the rulebook's vocabulary. "2 beams" is the SRD's own
# "Cantrip Upgrade" rule; "nonmagical plate" is its "Crafting Nonmagical Items". Neither
# heading names the selection, so both anchored paths refuse them, and both are exactly
# what the reader highlights while reading a book.


def test_a_selection_finds_the_rule_its_words_came_from():
    """The regression this path exists for, and the heading it must land on.

    Asserted on the heading rather than the passage because the heading is the stable
    contract: "2 beams" is the Eldritch Blast cantrip-upgrade rule, and the text of that
    rule may be reissued.
    """
    result = rules.gather_from_selection("2 beams")
    assert result["url"] == "context/srd/spells.md"
    assert result["passages"][0].startswith("## Eldritch Blast")
    assert "two beams" in result["passages"][0]


@pytest.mark.parametrize(
    "selection,heading",
    [
        # The words that identify the rule are in the section's body, not its heading -
        # which is why the anchored paths cannot take a selection at all.
        ("crackling energy", "Eldritch Blast"),
        ("nonmagical plate", "Crafting Nonmagical Items"),
        ("1d10 Force damage", "Damage against Multiple Targets"),
        ("Peel, Stabilize, Patch", "Stabilizing a Character"),
        ("30-ft range at level 5", "Multiattack"),
        # A selection that *is* a term the SRD defines, so this path must agree with the
        # glossary rather than finding something arbitrary.
        ("Help action", "Help [Action]"),
        ("Ritual", "Ritual Adept"),
    ],
)
def test_the_heading_a_selection_lands_on(selection, heading):
    result = rules.gather_from_selection(selection)
    headings = [
        line.removeprefix("## ")
        for line in result["passages"][0].splitlines()
        if line.startswith("## ")
    ]
    assert any(heading.lower() in h.lower() for h in headings), headings


@pytest.mark.parametrize(
    "selection",
    [
        # "rust" appears nowhere in the SRD's text and "flank" nowhere in its headings, so
        # neither selection has a rule to find. Reporting the gap is the honest outcome;
        # quoting nearby prose would read as sourced.
        "Rust Metal",
        "how does flanking work",
    ],
)
def test_a_selection_the_srd_cannot_speak_to_is_refused(selection):
    with pytest.raises(rules.RulesUnavailable):
        rules.gather_from_selection(selection)


@pytest.mark.parametrize(
    "selection",
    [
        # Generic words the rulebook uses everywhere. The anchored paths above find their
        # rules by heading, which is the signal this path does not have - so it must defer
        # to them rather than guess. Each of these is answered by `gather` or
        # `gather_inferred` today, so refusing here costs a reader nothing.
        "spell attack",
        "ranged spell attack",
        "damage",
        "action",
    ],
)
def test_the_selection_path_defers_what_the_anchored_paths_can_answer(selection):
    """Coverage is the gate, and this is why it is drawn where it is.

    A score threshold was tried first and rejected: the right answer for "Help action"
    scored *lower* than a wrong one for "how does a spear work". What actually separates
    them is how much of the selection consists of words the SRD uses at all.
    """
    with pytest.raises(rules.RulesUnavailable):
        rules.gather_from_selection(selection)
    assert rules._coverage(rules._selection_weights(selection)) < rules._MIN_COVERAGE


def test_the_selection_path_reports_a_missing_corpus():
    with pytest.raises(rules.RulesUnavailable, match="No SRD text found"):
        rules.gather_from_selection("2 beams", files=[])


def test_the_selection_path_quotes_the_selection_back_when_it_refuses():
    """The refusal is read by someone who just highlighted something, so it has to say what
    it could not explain - and stay one line wide when the selection is a whole sentence."""
    long_selection = "Rust Metal corrodes nonmagical metal plating whenever the flumph is flanked"
    with pytest.raises(rules.RulesUnavailable) as caught:
        rules.gather_from_selection(long_selection)
    assert "Rust Metal" in str(caught.value)
    assert len(str(caught.value).splitlines()) == 1
    assert "..." in str(caught.value)


# --- attaching documents named by a selection ----------------------------------
#
# A book's sentence names the spells it is about, and those names have to become their rules
# or the answer can only report that the SRD does not cover them. Matching is case-sensitive
# and whole-word, exactly as the markdown renderer links mentions - two rules would eventually
# disagree about whether a faint mention counts, and the disagreement is invisible in the
# answer.


def test_the_spells_named_by_a_selection_are_attached():
    """The session that prompted this, verbatim."""
    selection = (
        "If Repelling Blast misses or you need a second angle, Thorn Whip is a 30-ft "
        "melee spell attack for 2d6 and pulls the rust monster 10 ft toward you"
    )
    names = [document["name"] for document in rules.mentioned_documents(selection)]
    assert "Thorn Whip" in names
    assert "Repelling Blast" in names


def test_an_attached_document_carries_its_own_text():
    """The document is the *rules*, not a pointer to them: the prompt gets the text."""
    document = rules.resolve_attachments(["Thorn Whip"])[0]
    # The cantrip-upgrade line is what makes "2d6 at level 5" answerable, and it appears
    # nowhere else in the SRD.
    assert "1d6" in document["text"]
    assert document["source"] == rules.CORPUS_SOURCE


def test_an_invocation_attaches_as_an_invocation_not_a_spell():
    """An Eldritch Invocation is a class feature. Folding one in as a spell would be the
    category error `/api/invocation` exists to avoid, and the source must say which it is.

    Asserted on the *effect* rather than the name, because that is the part a spell-shaped
    answer would get wrong: "Repelling Blast" is not a spell with a range and a duration, it
    is a modification to a cantrip the character already knows.
    """
    document = rules.resolve_attachments(["Repelling Blast"])[0]
    assert document["source"] == rules.RULES_SOURCE
    assert "push the creature up to 10 feet" in document["text"]
    # A spell description would carry a stats line. This must not, or it would read as
    # something castable.
    assert "_Level" not in document["text"]


@pytest.mark.parametrize(
    "text,expected",
    [
        # Capitalisation is the signal. 132 of the corpus's spells are single common words,
        # so a case-insensitive match would attach the *Light* cantrip to a sentence about a
        # torch - and the reader would see a document they never asked about.
        ("the light of the fire and a deep sleep", []),
        # A single-word name is not matched inside a longer proper name. "Healing Light" is
        # one feature; its trailing "Light" is not the cantrip.
        ("Healing Light gives the fighter a boost", []),
        ("cast Light on the fighter's shield", ["Light"]),
        # Longest-first, so a name containing another name resolves as the longer one.
        ("a Daylight spell fills the room", ["Daylight"]),
        ("Ray of Frost and Thorn Whip", ["Ray of Frost", "Thorn Whip"]),
        # Multi-word names are exempt from the preceding-word rule, so a capitalised word
        # before them does not suppress the match.
        ("Use Eldritch Blast.", ["Eldritch Blast"]),
    ],
)
def test_a_mention_is_a_capitalised_whole_name(text, expected):
    assert sorted(d["name"] for d in rules.mentioned_documents(text)) == sorted(expected)


def test_attachment_resolution_dedupes_and_ignores_unknown_names():
    """The names come from the UI, so a name it does not know must not invent a document."""
    documents = rules.resolve_attachments(
        ["Thorn Whip", "Repelling Blast", "Nonsense Spell", "Thorn Whip"])
    assert [document["name"] for document in documents] == ["Thorn Whip", "Repelling Blast"]


def test_attachments_are_capped():
    """Each document is a full spell description, so a paragraph naming six spells must not
    arrive with six behind it."""
    selection = "Eldritch Blast, Ray of Frost, Thorn Whip, Mending, Light, Detect Magic"
    assert len(rules.mentioned_documents(selection)) <= rules._ATTACHMENT_LIMIT


# --- the vector lane over the indexed rulebook ---------------------------------


class _IndexDB:
    """A store whose similarity search returns canned SRD hits.

    The lane's job is to turn *chunks* back into *sections*, so the fake returns several
    chunks of the same section - which is what the real index does, and what a fake with one
    row per section would not exercise.
    """

    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def similarity_search_with_score(self, query, k=4, filter=None, **kwargs):
        self.filters.append(filter)
        return [(FakeDoc(**row), 0.1 * index) for index, row in enumerate(self.rows[:k])]

    def get(self, where=None, include=None, **kwargs):
        rows = [row for row in self.rows if _matches(row, where)]
        return {"metadatas": rows, "ids": [row["filename"] for row in rows]}


def _matches(row, where):
    if not where:
        return True
    for key, expected in where.items():
        if key == "$and":
            if not all(_matches(row, c) for c in expected):
                return False
        elif isinstance(expected, dict):
            continue
        elif row.get(key) != expected:
            return False
    return True


class FakeDoc:
    def __init__(self, **metadata):
        self.metadata = metadata
        self.page_content = metadata.pop("_text", "chunk text")


def _srd_row(name, document, slug, text="chunk text"):
    return {"spell_name": name, "filename": document, "doc_type": "srd",
            "document": document, "slug": slug, "level": 0, "is_spell": False,
            "_text": text}


def test_the_vector_lane_asks_only_for_srd_rows():
    """A rule is not a spell, so the lane must not be handed the spell corpus."""
    db = _IndexDB([_srd_row("Cover", "rules-glossary", "cover")])
    rules.gather_from_index(db, "how much cover do I get")
    assert db.filters == [{"doc_type": "srd"}]


def test_the_vector_lane_returns_the_whole_section_not_the_chunk():
    """A chunk is a 1200-character window that can begin mid-table; the section is the rule."""
    db = _IndexDB([_srd_row("Cover", "rules-glossary", "cover")])
    found = rules.gather_from_index(db, "how much cover do I get")
    assert "+2" in found["text"]
    assert "Half Cover" in found["text"]


def test_the_vector_lane_collapses_chunks_of_one_section():
    """Several chunks of one section are one passage, not three."""
    db = _IndexDB([
        _srd_row("Cover", "rules-glossary", "cover"),
        _srd_row("Cover", "rules-glossary", "cover"),
        _srd_row("Cover", "rules-glossary", "cover"),
    ])
    found = rules.gather_from_index(db, "cover")
    assert len(found["passages"]) == 1


def test_the_vector_lane_links_to_the_section_it_found():
    """The citation has to open the rule, not the top of the rulebook."""
    db = _IndexDB([_srd_row("Cover", "rules-glossary", "cover")])
    found = rules.gather_from_index(db, "cover")
    assert found["url"].endswith("#cover")


def test_the_vector_lane_refuses_when_the_index_has_no_rules():
    """An empty result is a gap to report, not an answer to invent."""
    with pytest.raises(rules.RulesUnavailable, match="no section matching"):
        rules.gather_from_index(_IndexDB([]), "how does flanking work")


def test_the_vector_lane_falls_back_to_the_chunk_when_the_section_is_gone():
    """The index can be older than the corpus - a heading renamed since the last rebuild.

    The chunk text is still real SRD text, so it is used rather than dropping the hit.
    """
    db = _IndexDB([_srd_row("Renamed", "rules-glossary", "no-such-slug",
                            text="the rule as it was indexed")])
    found = rules.gather_from_index(db, "something")
    assert "the rule as it was indexed" in found["text"]


def test_class_context_files_are_derived_from_the_directory():
    """Derived, not listed: a list would name files that do not exist, and a link to a file
    that is not there is worse than no link."""
    found = [str(path.relative_to(config.CONTEXT_DIR_PATH)) for path in rules.class_context_files()]
    assert "classes/warlock/base.md" in found
    assert "classes/warlock/pact/tome.md" in found
    assert "classes/warlock/subclass/celestial.md" in found
    # Class-wide rules first, then pacts, then patrons - the order a reader meets them in.
    assert found.index("classes/warlock/base.md") < found.index("classes/warlock/pact/tome.md")
    assert found.index("classes/warlock/pact/tome.md") < found.index(
        "classes/warlock/subclass/celestial.md"
    )


def test_a_class_context_path_cannot_escape_its_directory():
    """The path arrives from a URL, so it is checked rather than trusted.

    Without this the endpoint would read any file on the machine and serve it as a rule.
    """
    for attempt in (
        "../../../../etc/passwd",
        "/etc/passwd",
        "warlock/../../../AGENTS.md",
        "warlock/base.txt",
    ):
        with pytest.raises(rules.RulesUnavailable):
            rules.class_context_path(attempt)


def test_a_class_context_name_is_the_phrase_the_prose_uses():
    """The name is what the front end searches generated prose for, so it has to be the
    phrase the prose writes - not the filename, which is a path segment."""
    assert rules._linkable_name("Warlock - base class rules (D&D 5.5e / 2024)") == "Warlock"
    assert rules._linkable_name("Celestial Patron (D&D 5.5e / 2024)") == "Celestial Patron"
    assert rules._linkable_name("Pact of the Tome (D&D 5.5e / 2024)") == "Pact of the Tome"
    # A title with no edition tag or clause is already the name.
    assert rules._linkable_name("Something") == "Something"
