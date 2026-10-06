import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api'
import { asciiDigits, leaveFor } from '../signIn'

describe('asciiDigits', () => {
  it('reads Arabic-Indic and Persian digits as the same code', () => {
    expect(asciiDigits('١٢٣٤٥٦')).toBe('123456')
    expect(asciiDigits('۰۹۸۷۶۵')).toBe('098765')
    expect(asciiDigits('12 34-56')).toBe('123456')
  })
})

describe('leaveFor', () => {
  const assign = vi.fn()
  afterEach(() => {
    vi.unstubAllGlobals()
    assign.mockReset()
  })
  const at = (href: string) => vi.stubGlobal('window', { location: { href, assign } })

  it('goes to a web address', () => {
    at('https://harak.example/login')
    leaveFor('https://idp.example/auth?state=x')
    expect(assign).toHaveBeenCalledWith('https://idp.example/auth?state=x')
  })

  it.each(['javascript:alert(document.domain)//?x=1', 'data:text/html,<script>1</script>', 'vbscript:x'])(
    'never runs %s in Harak’s origin',
    (address) => {
      at('https://harak.example/login')
      expect(() => leaveFor(address)).toThrow(ApiError)
      expect(assign).not.toHaveBeenCalled()
    },
  )
})
