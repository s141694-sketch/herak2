import { Server } from '@hocuspocus/server'

export interface CollabServerOptions {
  port: number
  /** Service name reported by the health endpoint. */
  name?: string
}

/**
 * Creates the collaboration server. Phase 1 only needs it to run and report
 * health; per-document authentication and persistence arrive in phase 3.
 */
export function createCollabServer(options: CollabServerOptions): Server {
  return new Server({
    port: options.port,
    name: options.name ?? 'harak2-collab',
    onRequest({ request, response }) {
      if (request.url === '/health') {
        response.writeHead(200, { 'Content-Type': 'application/json' })
        response.end(JSON.stringify({ status: 'ok', service: 'collab' }))
        // A rejection with no value tells Hocuspocus the request was handled here.
        return Promise.reject()
      }
      return Promise.resolve()
    },
  })
}
