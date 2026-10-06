import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { api, ApiError, errorCode, type Membership } from './api'
import { useAuth } from './auth'

/** Sends the browser to an identity provider's page. Only http(s): an address the provider published must never
 * run as a script in Harak's own origin (a javascript: URL). */
export function leaveFor(address: string): void {
  const url = new URL(address, window.location.href)
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    throw new ApiError(409, 'provider_endpoint_invalid', 'the provider published an address that is not a web page')
  }
  window.location.assign(url.href)
}

const DIGITS: Record<string, string> = Object.fromEntries(
  [...'٠١٢٣٤٥٦٧٨٩', ...'۰۱۲۳۴۵۶۷۸۹'].map((digit, index) => [digit, String(index % 10)]),
)

/** The digits of a code as typed, Arabic-Indic ones (an Arabic keyboard) as their ASCII digits; the rest dropped. */
export function asciiDigits(value: string): string {
  return [...value].map((char) => DIGITS[char] ?? char).join('').replace(/\D/g, '')
}

/** What choosing the organization does, said before it is chosen (a translation key). */
export function entryHint(membership: Membership): string {
  if (membership.sso_required) return 'organization.ssoRequired'
  if (membership.password_required) return 'organization.passwordRequired'
  if (membership.mfa_required) return 'organization.mfaRequired'
  return `roles.${membership.role}`
}

/** Enters one of the person's organizations the way it asks to be entered: through its provider (D66), after a
 * password sign-in (D71), after setting up a second factor (D67), or straight away. */
export function useEnterOrganization() {
  const { i18n } = useTranslation()
  const navigate = useNavigate()
  const { session, logout, switchOrganization } = useAuth()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const enter = async (membership: Membership) => {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      if (membership.sso_required) {
        const { redirect } = await api.startSso({ organization: membership.organization.id }, i18n.language)
        leaveFor(redirect)
        return // stays busy while the browser leaves
      }
      if (membership.password_required) {
        const email = session?.user.email ?? ''
        await logout()
        navigate(`/login?email=${encodeURIComponent(email)}&reason=password_required`, { replace: true })
        return
      }
      if (membership.mfa_required) {
        navigate('/account/security')
      } else {
        await switchOrganization(membership.organization.id)
      }
    } catch (caught) {
      setError(errorCode(caught))
    }
    setBusy(false)
  }
  return { enter, busy, error }
}
