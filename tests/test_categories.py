"""The shared category vocabulary: canonical IDs, the learned mapping, filters."""

import pytest

from stores import categories
from stores.browse import narrow
from stores.categories import Mapping, build_mapping, canonical_id, canonical_names


TEJ = "alapveto-elelmiszerek/tejtermekek"
PEK = "alapveto-elelmiszerek/pekaru"


@pytest.fixture(autouse=True)
def clear_cache():
    categories.invalidate()
    yield
    categories.invalidate()


def use_mapping(monkeypatch, mapping):
    monkeypatch.setattr(categories, "mapping", lambda: mapping)


def sample_mapping():
    return Mapping(
        categories={
            TEJ: {"names": ["Alapvető élelmiszerek", "Tejtermékek"], "counts": {"tesco": 120, "auchan": 60}},
            PEK: {"names": ["Alapvető élelmiszerek", "Pékáru"], "counts": {"tesco": 80, "auchan": 0}},
        },
        paths_by_store={"auchan": {
            ("Élelmiszer", "Tej, tojás", "Tej"): TEJ,
            ("Élelmiszer", "Tej, tojás", "Sajt"): TEJ,
        }},
    )


# -- canonical identifiers ----------------------------------------------------------

@pytest.mark.parametrize("path, expected", [
    (["Alapvető élelmiszerek", "Tejtermékek", "Tej", "UHT tej"], TEJ),
    (["Alapvető élelmiszerek", "Tejtermékek"], TEJ),
    ([" Alapvető élelmiszerek ", "Tejtermékek"], TEJ),
    (["Alapvető élelmiszerek"], None),          # one level cannot be told apart
    (["Alapvető élelmiszerek", None, "Tej"], TEJ.replace("tejtermekek", "tej")),
    ([], None),
    (None, None),
])
def test_canonical_id(path, expected):
    assert canonical_id(path) == expected


def test_canonical_names_keep_the_original_spelling():
    assert canonical_names(["Alapvető élelmiszerek", "Tejtermékek", "Tej"]) == (
        "Alapvető élelmiszerek", "Tejtermékek")


# -- learning the mapping -----------------------------------------------------------

def pairs(path, category, count):
    return [(path, category)] * count


def test_a_path_maps_to_the_category_its_linked_products_agree_on():
    entries = build_mapping(pairs(("Élelmiszer", "Tej"), TEJ, 4))
    assert entries == [{"path": ["Élelmiszer", "Tej"], "category": TEJ, "support": 4,
                        "votes": 4, "confidence": 1.0, "depth": 2}]


def test_too_few_linked_products_leave_a_path_unmapped():
    assert build_mapping(pairs(("Élelmiszer", "Tej"), TEJ, 2)) == []


def test_a_disagreeing_path_is_left_unmapped_rather_than_guessed():
    votes = pairs(("Élelmiszer", "Vegyes"), TEJ, 5) + pairs(("Élelmiszer", "Vegyes"), PEK, 5)
    assert build_mapping(votes) == []


def test_a_clear_majority_wins_despite_some_disagreement():
    votes = pairs(("Élelmiszer", "Tej"), TEJ, 9) + pairs(("Élelmiszer", "Tej"), PEK, 1)
    entry, = build_mapping(votes)
    assert (entry["category"], entry["support"], entry["votes"], entry["confidence"]) == (TEJ, 9, 10, 0.9)


def test_an_unsupported_leaf_falls_back_to_its_parent():
    """A niche leaf with one linked product still lands where its parent does."""
    votes = (pairs(("Élelmiszer", "Tej, tojás", "Tej"), TEJ, 4)
             + pairs(("Élelmiszer", "Tej, tojás", "Kefir"), TEJ, 1))
    kefir = next(e for e in build_mapping(votes) if e["path"][-1] == "Kefir")
    assert (kefir["category"], kefir["depth"]) == (TEJ, 2)


def test_products_with_no_linked_counterpart_still_map_through_their_path():
    votes = pairs(("Élelmiszer", "Tej"), TEJ, 3) + [(("Élelmiszer", "Tej"), None)] * 50
    entry, = build_mapping(votes)
    assert entry["support"] == 3 and entry["category"] == TEJ


def test_an_unrelated_path_with_no_votes_is_not_invented():
    votes = pairs(("Élelmiszer", "Tej"), TEJ, 3) + [(("Műszaki", "Tévé"), None)]
    assert [entry["path"] for entry in build_mapping(votes)] == [["Élelmiszer", "Tej"]]


def test_empty_path_segments_are_ignored():
    entries = build_mapping(pairs(("Élelmiszer", "", None, "Tej"), TEJ, 3))
    assert entries[0]["path"] == ["Élelmiszer", "Tej"]


# -- filtering ----------------------------------------------------------------------

def test_unknown_category_is_rejected(monkeypatch):
    use_mapping(monkeypatch, sample_mapping())
    with pytest.raises(categories.UnknownCategory):
        categories.resolve("no-such/category")


@pytest.mark.parametrize("requested", ["", None, "   "])
def test_no_category_means_no_filter(monkeypatch, requested):
    use_mapping(monkeypatch, sample_mapping())
    assert categories.resolve(requested) is None
    assert categories.query_for("tesco", None) is None


def test_the_canonical_store_is_queried_by_its_own_field_names(monkeypatch):
    use_mapping(monkeypatch, sample_mapping())
    assert categories.query_for("tesco", TEJ) == {
        "super_department_name": "Alapvető élelmiszerek", "department_name": "Tejtermékek"}


def test_a_mapped_store_is_queried_by_its_own_paths(monkeypatch):
    use_mapping(monkeypatch, sample_mapping())
    assert categories.query_for("auchan", TEJ) == {"category_path": {"$in": [
        ["Élelmiszer", "Tej, tojás", "Sajt"],
        ["Élelmiszer", "Tej, tojás", "Tej"],
    ]}}


def test_a_store_with_nothing_in_the_category_matches_nothing(monkeypatch):
    """Not the same as no filter: an empty result is the honest answer."""
    use_mapping(monkeypatch, sample_mapping())
    assert categories.query_for("auchan", PEK) == {"category_path": {"$in": []}}


@pytest.mark.parametrize("store_id, path, category, expected", [
    ("tesco", ["Alapvető élelmiszerek", "Tejtermékek", "Tej"], TEJ, True),
    ("tesco", ["Alapvető élelmiszerek", "Pékáru"], TEJ, False),
    ("auchan", ["Élelmiszer", "Tej, tojás", "Sajt"], TEJ, True),
    ("auchan", ["Élelmiszer", "Tej, tojás"], TEJ, False),   # an unmapped parent path
    ("auchan", ["Műszaki", "Tévé"], TEJ, False),
    ("auchan", ["Műszaki", "Tévé"], None, True),            # no filter passes everything
])
def test_matches_agrees_with_the_query(store_id, path, category, expected, monkeypatch):
    use_mapping(monkeypatch, sample_mapping())
    assert categories.matches(store_id, path, category) is expected


def test_the_mongo_query_and_the_predicate_select_the_same_products(monkeypatch):
    """The two filters are separate implementations of one rule, for text and vector hits."""
    use_mapping(monkeypatch, sample_mapping())
    catalogue = [
        {"category_path": ["Élelmiszer", "Tej, tojás", "Tej"]},
        {"category_path": ["Élelmiszer", "Tej, tojás", "Sajt"]},
        {"category_path": ["Élelmiszer", "Tej, tojás"]},
        {"category_path": ["Műszaki", "Tévé"]},
    ]
    allowed = categories.query_for("auchan", TEJ)["category_path"]["$in"]
    by_query = [doc for doc in catalogue if doc["category_path"] in allowed]
    by_predicate = [doc for doc in catalogue if categories.matches("auchan", doc["category_path"], TEJ)]
    assert by_query == by_predicate


def test_narrow_keeps_both_clauses():
    assert narrow({"$text": {"$search": "tej"}}, {"category_path": {"$in": [["a"]]}}) == {
        "$and": [{"$text": {"$search": "tej"}}, {"category_path": {"$in": [["a"]]}}]}
    assert narrow({"$or": [{"name": 1}]}, None) == {"$or": [{"name": 1}]}


# -- the listing the API serves -----------------------------------------------------

def test_listing_reports_per_store_counts(monkeypatch):
    use_mapping(monkeypatch, sample_mapping())
    rows = sample_mapping().listing(["tesco", "auchan"])
    assert [(row["id"], row["products"]) for row in rows] == [(PEK, 80), (TEJ, 180)]


def test_listing_leaves_out_categories_the_selected_stores_do_not_sell():
    rows = sample_mapping().listing(["auchan"])
    assert [row["id"] for row in rows] == [TEJ]


def test_listing_without_a_store_selection_keeps_every_category():
    assert len(sample_mapping().listing()) == 2


# -- degraded mode ------------------------------------------------------------------

def test_an_unavailable_mapping_turns_filters_off_rather_than_breaking_search(monkeypatch):
    use_mapping(monkeypatch, categories.EMPTY)
    assert categories.mapping().listing(["tesco"]) == []
    assert categories.query_for("tesco", None) is None
    with pytest.raises(categories.UnknownCategory):
        categories.resolve(TEJ)
