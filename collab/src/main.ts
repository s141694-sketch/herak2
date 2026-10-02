import { createCollabServer } from './server.js'

function required(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is required`)
  return value
}

const port = Number(process.env.PORT ?? 1234)
const server = createCollabServer({ port, tokenSecret: required('COLLAB_TOKEN_SECRET') })

server.listen().then(() => console.log(JSON.stringify({ event: 'collab.listening', port })))

for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => {
    server.hocuspocus.flushPendingStores()
    server.destroy().then(() => process.exit(0))
  })
}
