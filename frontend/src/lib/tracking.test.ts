import { describe, expect, it } from 'vitest'
import { lowerIsBetter, metricLabel } from './tracking'
import { fromPipelineSpec } from './serialize'
import { usePipelineStore } from '../store/pipelineStore'
import { trackingOf, type PipelineSpec } from '../types/pipeline'

describe('run comparison helpers', () => {
  it('knows which metrics are better when smaller', () => {
    expect(lowerIsBetter('n6.rmse')).toBe(true)
    expect(lowerIsBetter('n6.mae')).toBe(true)
    expect(lowerIsBetter('n6.accuracy')).toBe(false)
    expect(lowerIsBetter('n6.f1')).toBe(false)
  })

  it('labels metrics with the node they came from', () => {
    expect(metricLabel('n5.accuracy', { n5: 'Metrics Node' })).toBe('Metrics Node · accuracy')
    expect(metricLabel('n9.r2', {})).toBe('n9 · r2')
  })
})

describe('pipeline metadata (tracking settings) round trip', () => {
  const spec: PipelineSpec = {
    version: 2, name: 'churn', description: 'weekly churn model',
    metadata: { tracking: { enabled: true, connection: 'prod-mlflow', experiment: 'churn-v2' }, owner: 'ds-team' },
    nodes: [{ id: 'n1', type: 'csv_loader', position: { x: 0, y: 0 }, config: {} }], edges: [],
  }

  it('keeps name, description and metadata through load and save', () => {
    const { nodes, edges, meta } = fromPipelineSpec(spec)
    usePipelineStore.getState().loadPipeline(nodes, edges, meta)
    const out = usePipelineStore.getState().toPipelineSpec()
    expect(out.name).toBe('churn')
    expect(out.description).toBe('weekly churn model')
    expect(out.metadata).toEqual(spec.metadata)
  })

  it('fills tracking defaults for older pipelines', () => {
    const t = trackingOf({ name: 'x', description: '', metadata: {} })
    expect(t).toEqual({ enabled: false, connection: '', experiment: '', log_models: true, log_code: true })
  })

  it('a template load resets metadata instead of inheriting the previous pipeline\'s tracking', () => {
    const { nodes, edges, meta } = fromPipelineSpec(spec)
    usePipelineStore.getState().loadPipeline(nodes, edges, meta)
    usePipelineStore.getState().loadPipeline([], [])
    expect(trackingOf(usePipelineStore.getState().meta).enabled).toBe(false)
  })
})

describe('metric ordering for the Runs view', () => {
  it('puts model-quality metrics before bookkeeping ones', async () => {
    const { sortMetrics, isQualityMetric } = await import('./tracking')
    expect(sortMetrics(['n1.rows', 'n6.f1', 'n3.train_rows', 'n6.accuracy'])).toEqual(['n6.accuracy', 'n6.f1', 'n1.rows', 'n3.train_rows'])
    expect(isQualityMetric('n6.roc_auc')).toBe(true)
    expect(isQualityMetric('n1.rows')).toBe(false)
  })
})
