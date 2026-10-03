import { createCollabServer } from './server.js'
import { DjangoStore } from './store.js'

function required(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is required`)
  return value
}

const port = Number(process.env.PORT ?? 1234)
const service = createCollabServer({
  port,
  tokenSecret: required('COLLAB_TOKEN_SECRET'),
  serviceSecret: required('COLLAB_SERVICE_SECRET'),
  store: new DjangoStore(required('DJANGO_INTERNAL_URL'), required('COLLAB_SERVICE_SECRET')),
})

service.listen().then(() => console.log(JSON.stringify({ event: 'collab.listening', port })))

// Containers are given about ten seconds to stop: pending saves get eight, then the process exits regardless.
for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => {
    service.destroy(8000).finally(() => process.exit(0))
  })
}
