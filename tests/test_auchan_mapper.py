"""Mapping real auchan.hu API products (fixture from a 2026-09-17 crawl)."""

import json
from pathlib import Path

import pytest

from stores.auchan import mapper, repository


FIXTURE = Path(__file__).parent / "fixtures" / "auchan" / "product_list.json"


@pytest.fixture(scope="module")
def products():
    results = json.loads(FIXTURE.read_text(encoding="utf-8"))["results"]
    return {product["id"]: product for product in results}


def test_regular_product(products):
    fields = mapper.document_fields(products[942428])
    assert fields["store_product_id"] == "942428"
    assert fields["name"] == "Mizo protein vaníliás tejital 500 ml"
    assert fields["brand"] == "Mizo"
    assert fields["ean"] == "5998200485596" and fields["gtin_norm"] == "5998200485596"
    assert fields["category_path"][0] == "Friss élelmiszer" and len(fields["category_path"]) == 4
    assert fields["prices"] == {"regular": 649.0, "promo": None, "loyalty": None, "unit_price": 1298.0, "unit": "l"}
    assert fields["pack_size"] == 0.5 and fields["pack_unit"] == "l"
    assert fields["availability"] == "available"
    assert fields["url"] == "https://auchan.hu/shop/mizo-protein-vanilias-tejital-500-ml.p-981459"
    assert not fields["own_brand"] and not fields["loyalty_offer"]


def test_discounted_product(products):
    fields = mapper.document_fields(products[632009])
    assert fields["prices"]["regular"] == 969.0
    assert fields["prices"]["promo"] == 629.0
    assert fields["prices"]["unit"] == "kg"
    assert fields["promo_valid_to"] == "2026-09-23T23:59:59+02:00"


def test_loose_product_uses_price_per_kg(products):
    fields = mapper.document_fields(products[469034])
    assert fields["is_loose"] is True
    assert fields["prices"]["regular"] == 7499.0
    assert fields["pack_size"] == 1.0 and fields["pack_unit"] == "kg"
    assert fields["own_brand"] is True


def test_loyalty_price_from_anonymous_unit_price(products):
    fields = mapper.document_fields(products[658866])
    # 784 Ft/l card unit price x 5 l
    assert fields["prices"]["loyalty"] == 3920.0
    assert fields["prices"]["regular"] == 4899.0
    assert fields["loyalty_offer"] is True
    assert fields["loyalty_valid_to"] == "2026-09-23T23:59:59+02:00"


def test_offer_from_stored_document(products):
    fields = mapper.document_fields(products[658866])
    current = {"date": "2026-09-17", **fields["prices"]}
    doc = {"_id": "658866", **{k: v for k, v in fields.items() if k != "prices"}, "current": current}
    offer = mapper.offer_from_doc(doc)
    assert offer["ref"] == "auchan:658866"
    assert offer["prices"]["loyalty"] == 3920.0
    assert offer["effective_price"] == 3920.0
    assert offer["gtin"] == "5999880746502"
    assert offer["price_date"] == "2026-09-17"


def test_product_without_variant_is_rejected():
    with pytest.raises(mapper.UnexpectedProductShape):
        mapper.document_fields({"id": 1, "selectedVariant": None})


@pytest.mark.parametrize("text, slug", [
    ("Coca-Cola colaízű szénsavas üdítőital 300 ml", "coca-cola-colaizu-szensavas-uditoital-300-ml"),
    ("Sió erdei piros bogyós smoothie 0,25 l", "sio-erdei-piros-bogyos-smoothie-025-l"),
    ("  Ő & Ű  ", "o-u"),
])
def test_slugify(text, slug):
    assert mapper.slugify(text) == slug


def test_details_text_keeps_description_and_ingredients():
    sections = [
        {"sectionType": "description", "description": "  Finom  "},
        {"sectionType": "ingredients", "description": "Víz; Cukor"},
        {"sectionType": "parameterList", "parameters": []},
        "garbage",
    ]
    assert mapper.details_text(sections) == {"description": "Finom", "ingredients": "Víz; Cukor"}


def test_history_replaces_todays_entry_and_keeps_order():
    history = [{"date": "2026-09-16", "regular": 10}, {"date": "2026-09-17", "regular": 11}]
    merged = repository._merge_history(history, "2026-09-17", {"date": "2026-09-17", "regular": 9})
    assert merged == [{"date": "2026-09-16", "regular": 10}, {"date": "2026-09-17", "regular": 9}]
    appended = repository._merge_history(history[:1], "2026-09-18", {"date": "2026-09-18", "regular": 8})
    assert [row["date"] for row in appended] == ["2026-09-16", "2026-09-18"]


def test_browse_sort_fields_use_the_best_price():
    fields = repository.browse_sort_fields({"regular": 1000.0, "promo": None, "loyalty": 800.0})
    assert fields == {"version": 1, "has_price": True, "effective_price": 800.0,
                      "has_discount": True, "discount_ratio": pytest.approx(0.2)}
