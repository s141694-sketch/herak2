import { createCollabServer } from './server.js'

const port = Number(process.env.PORT ?? 1234)
const server = createCollabServer({ port })

server.listen().then(() => console.log(JSON.stringify({ event: 'collab.listening', port })))

for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => {
    server.destroy().then(() => process.exit(0))
  })
}
