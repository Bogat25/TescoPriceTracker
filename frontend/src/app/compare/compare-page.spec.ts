import { GroupHistory, HistoryRow } from '../services/catalog.service';
import { alignSeries, bestOfDay } from './compare-page';

function day(date: string, regular: number | null, promo: number | null = null, loyalty: number | null = null): HistoryRow {
  return { date, regular, promo, loyalty, unit_price: null, unit: null, availability: null };
}

function series(ref: string, store: string, history: HistoryRow[]): GroupHistory['series'][number] {
  return { store, ref, history };
}

describe('compare page history chart', () => {
  it('plots the price a shopper would actually pay', () => {
    expect(bestOfDay(day('2026-09-17', 499, 449, 399))).toBe(399);
    expect(bestOfDay(day('2026-09-17', 499, null, null))).toBe(499);
    expect(bestOfDay(day('2026-09-17', null))).toBeNull();
  });

  it('puts both stores on one timeline, with gaps where a store has no price', () => {
    const { labels, values } = alignSeries([
      series('tesco:1', 'tesco', [day('2026-09-15', 400), day('2026-09-17', 420)]),
      series('auchan:2', 'auchan', [day('2026-09-16', 380), day('2026-09-17', 390)]),
    ], 0);

    expect(labels).toEqual(['2026-09-15', '2026-09-16', '2026-09-17']);
    expect(values['tesco:1']).toEqual([400, null, 420]);
    expect(values['auchan:2']).toEqual([null, 380, 390]);
  });

  it('keeps only the chosen range', () => {
    const today = new Date('2026-09-17T00:00:00Z');
    const history = [day('2026-06-01', 300), day('2026-09-10', 320), day('2026-09-17', 340)];

    const quarter = alignSeries([series('tesco:1', 'tesco', history)], 90, today);
    expect(quarter.labels).toEqual(['2026-09-10', '2026-09-17']);

    const month = alignSeries([series('tesco:1', 'tesco', history)], 30, today);
    expect(month.labels).toEqual(['2026-09-10', '2026-09-17']);

    const everything = alignSeries([series('tesco:1', 'tesco', history)], 0, today);
    expect(everything.labels).toHaveLength(3);
  });

  it('sorts dates that arrive out of order', () => {
    const { labels, values } = alignSeries([
      series('tesco:1', 'tesco', [day('2026-09-17', 420), day('2026-09-15', 400)]),
    ], 0);
    expect(labels).toEqual(['2026-09-15', '2026-09-17']);
    expect(values['tesco:1']).toEqual([400, 420]);
  });

  it('has nothing to draw for a product with no history', () => {
    expect(alignSeries([], 90)).toEqual({ labels: [], values: {} });
    expect(alignSeries([series('tesco:1', 'tesco', [])], 90)).toEqual({ labels: [], values: { 'tesco:1': [] } });
  });
});
