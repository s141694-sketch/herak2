import { jwtVerify } from 'jose'

/** What a verified token grants: one user, one document, read or write. */
export interface Grant {
  userId: string
  organizationId: number
  versionId: number
  document: string
  mode: 'read' | 'write'
  name: string
  /** When the token stops vouching for the connection (epoch milliseconds). */
  expiresAt: number
}

export class AuthenticationRefused extends Error {}

export async function verifyToken(token: string, documentName: string, secret: string): Promise<Grant> {
  if (!token) throw new AuthenticationRefused('missing token')
  let payload: Record<string, unknown>
  try {
    ;({ payload } = await jwtVerify(token, new TextEncoder().encode(secret), {
      issuer: 'harak2-api',
      audience: 'harak2-collab',
      algorithms: ['HS256'],
    }))
  } catch (error) {
    throw new AuthenticationRefused(`invalid token: ${(error as Error).message}`)
  }
  if (payload.doc !== documentName) throw new AuthenticationRefused('token is for another document')
  if (payload.mode !== 'read' && payload.mode !== 'write') throw new AuthenticationRefused('unknown mode')
  return {
    userId: String(payload.sub),
    organizationId: Number(payload.org),
    versionId: Number(payload.ver),
    document: documentName,
    mode: payload.mode,
    name: String(payload.name ?? ''),
    expiresAt: Number(payload.exp) * 1000,
  }
}
