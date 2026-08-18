# Tesco GraphQL contract

The deployable product selection set lives in `mongo/queries.py` and is covered
by `tests/test_scraper_contract.py`.

Tesco's production endpoint currently disables GraphQL introspection. Do not
commit an old introspection dump as a schema source: it becomes stale without a
failure signal. The scheduler validates `FULL_PRODUCT_QUERY` against a current
catalog product before starting a run and aborts at error level if the contract
is rejected.

For an operator canary, run the scraper contract test or issue `GetProduct`
with the exact checked-in selection set and a current TPNC. A valid response
must contain `data.product` and no `errors` array.
