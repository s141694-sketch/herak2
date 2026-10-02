import { Server } from '@hocuspocus/server'

import { AuthenticationRefused, type Grant, verifyToken } from './auth.js'

export interface CollabServerOptions {
  port: number
  tokenSecret: string
  name?: string
}

export interface ConnectionContext {
  grant: Grant
}

/**
 * The collaboration service. Every connection presents a token issued by Django
 * for exactly one document; read grants open the connection read-only.
 */
export function createCollabServer(options: CollabServerOptions): Server<ConnectionContext> {
  return new Server<ConnectionContext>({
    port: options.port,
    name: options.name ?? 'harak2-collab',
    quiet: true,
    async onAuthenticate({ token, documentName, connectionConfig }) {
      try {
        const grant = await verifyToken(token, documentName, options.tokenSecret)
        connectionConfig.readOnly = grant.mode === 'read'
        return { grant }
      } catch (error) {
        if (error instanceof AuthenticationRefused) throw new Error('unauthorized')
        throw error
      }
    },
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
