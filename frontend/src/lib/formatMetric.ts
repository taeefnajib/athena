// How the Metrics tab shows a value. Only true ratios become percentages: an MAE of 0.8 or a MASE of 0.85
// is a number, not "80%". MAPE and sMAPE already arrive in percent units.

const RATIO = /^(mean_)?(accuracy|precision|recall|f1|roc_auc|pr_auc|ap_.+|coverage|balanced_accuracy|noise_share|.+_share|share)(_at_0\.5)?$/
const PERCENT_UNITS = /^(mean_)?s?mape$/
const COUNTS = /^(k|n|folds|horizon|season_length|clusters|rows|train_rows|test_rows|samples|trials|converged)$/

export function formatMetric(key: string, value: number): string {
  if (!Number.isFinite(value)) return '–'
  if (RATIO.test(key)) return `${(value * 100).toFixed(1)}%`
  if (PERCENT_UNITS.test(key)) return `${value.toFixed(2)}%`
  if (COUNTS.test(key) && Number.isInteger(value)) return value.toLocaleString()
  const a = Math.abs(value)
  if (a !== 0 && (a < 0.001 || a >= 1e6)) return value.toExponential(3)
  return a >= 1000 ? value.toLocaleString(undefined, { maximumFractionDigits: 1 }) : value.toPrecision(4).replace(/\.?0+$/, '')
}
