import { create } from 'zustand'
import { connectionsApi, type ConnectorSpec, type SavedConnection } from '../lib/connections'

interface ConnectionState {
  connectors: ConnectorSpec[]
  connections: SavedConnection[]
  loaded: boolean
  load: () => Promise<void>
  save: (name: string, type: string, config: Record<string, unknown>) => Promise<SavedConnection>
  remove: (name: string) => Promise<void>
}

export const useConnectionStore = create<ConnectionState>((set, get) => ({
  connectors: [],
  connections: [],
  loaded: false,
  load: async () => {
    const [connectors, connections] = await Promise.all([connectionsApi.connectors(), connectionsApi.list()])
    set({ connectors, connections, loaded: true })
  },
  save: async (name, type, config) => {
    const saved = await connectionsApi.save(name, type, config)
    set({ connections: [...get().connections.filter(c => c.name !== name), saved].sort((a, b) => a.name.localeCompare(b.name)) })
    return saved
  },
  remove: async (name) => {
    await connectionsApi.remove(name)
    set({ connections: get().connections.filter(c => c.name !== name) })
  },
}))
