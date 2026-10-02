import { Server } from '@hocuspocus/server'

// Minimal in-memory collaboration server for the spike. No persistence, no auth:
// authentication with short-lived tokens is a phase 3 concern.
const port = Number(process.env.PORT ?? 1234)

const server = new Server({
  port,
  async onConnect({ documentName }) {
    console.log(`[hocuspocus] connect ${documentName}`)
  },
})

server.listen().then(() => console.log(`[hocuspocus] listening on ${port}`))
