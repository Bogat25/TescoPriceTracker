import { Offer } from '../../services/catalog.service';
import { buildAlertRequest, lowestPrice } from './store-alert-form';

function offer(store: string, ref: string, price: number | null): Offer {
  return {
    store, ref, store_product_id: ref.split(':')[1], gtin: '5990000000011', group_id: 'g:5990000000011',
    is_weighed: false, name: 'Tej', brand: null, image_url: null, category_path: [], pack_size: null, pack_unit: null,
    availability: null, prices: { regular: price, promo: null, loyalty: null, unit_price: null, unit: null },
    effective_price: price, discount_ratio: 0, price_date: null, flags: [], url: null,
  };
}

const OFFERS = [offer('tesco', 'tesco:1', 400), offer('auchan', 'auchan:a1', 380)];

describe('store alert form', () => {
  it('uses the lowest price of the chosen stores', () => {
    expect(lowestPrice(OFFERS, ['tesco', 'auchan'])).toBe(380);
    expect(lowestPrice(OFFERS, ['tesco'])).toBe(400);
    expect(lowestPrice(OFFERS, [])).toBeNull();
  });

  it('sends the chosen stores with a group alert', () => {
    expect(buildAlertRequest('g:5990000000011', OFFERS, ['tesco'], 'PERCENTAGE_DROP', 10)).toEqual({
      target: 'g:5990000000011', stores: ['tesco'], alertType: 'PERCENTAGE_DROP', dropPercentage: 10, basePriceAtCreation: 400,
    });
  });

  it('watches only its own store for an offer alert', () => {
    expect(buildAlertRequest('auchan:a1', OFFERS, [], 'TARGET_PRICE', 350)).toEqual({
      target: 'auchan:a1', alertType: 'TARGET_PRICE', targetPrice: 350,
    });
  });

  it('explains what is wrong instead of sending', () => {
    expect(buildAlertRequest('g:5990000000011', OFFERS, [], 'TARGET_PRICE', 100)).toBe('alertform.err.stores');
    expect(buildAlertRequest('g:5990000000011', OFFERS, ['auchan'], 'TARGET_PRICE', 380)).toBe('alertform.err.below');
    expect(buildAlertRequest('g:5990000000011', OFFERS, ['auchan'], 'TARGET_PRICE', null)).toBe('alertform.err.target');
    expect(buildAlertRequest('g:5990000000011', OFFERS, ['auchan'], 'PERCENTAGE_DROP', 120)).toBe('alertform.err.pct');
  });
});
