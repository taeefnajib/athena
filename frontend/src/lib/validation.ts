import { NODE_REGISTRY, type PortType } from '../registry/nodeRegistry'

// Types that are compatible with a 'dataset' input port.
// X_* and y_* are DataFrames / Series produced by split nodes and can be
// fed into any node that expects a generic dataset (e.g. imputer, scaler).
const DATASET_COMPATIBLE: Set<PortType> = new Set([
  'dataset', 'X_train', 'y_train', 'X_test', 'y_test', 'X_val', 'y_val',
])

export function portsCompatible(src: PortType, tgt: PortType): boolean {
  if (src === tgt) return true
  // X_*/y_* → dataset  (split outputs into generic dataset inputs)
  if (tgt === 'dataset' && DATASET_COMPATIBLE.has(src)) return true
  // dataset → X_*/y_*  (generic dataset output into split-typed inputs, e.g. xy_to_dataset)
  if (src === 'dataset' && DATASET_COMPATIBLE.has(tgt)) return true
  return false
}

export function isValidConnection(
  sourceNodeType: string,
  sourcePortIdx: number,
  targetNodeType: string,
  targetPortIdx: number,
): boolean {
  const srcSpec = NODE_REGISTRY[sourceNodeType]
  const tgtSpec = NODE_REGISTRY[targetNodeType]
  if (!srcSpec || !tgtSpec) return false
  const srcPort = srcSpec.outputs[sourcePortIdx]
  const tgtPort = tgtSpec.inputs[targetPortIdx]
  if (!srcPort || !tgtPort) return false
  return portsCompatible(srcPort.type, tgtPort.type)
}
