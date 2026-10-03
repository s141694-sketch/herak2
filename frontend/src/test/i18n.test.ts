import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

import { parseAst } from 'rolldown/parseAst'
import { describe, expect, it } from 'vitest'

import ar from '../i18n/ar.json'
import { SAVE_ERROR_CODES } from '../live/useLiveDocument'
import en from '../i18n/en.json'

type Tree = { [key: string]: string | Tree }

function keys(tree: Tree, prefix = ''): string[] {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === 'string' ? [prefix + key] : keys(value, `${prefix}${key}.`),
  )
}

function lookup(tree: Tree, path: string): string | undefined {
  let node: string | Tree | undefined = tree
  for (const part of path.split('.')) node = typeof node === 'object' ? node[part] : undefined
  return typeof node === 'string' ? node : undefined
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'test' ? [] : sourceFiles(path)
    return /\.tsx?$/.test(name) && !name.endsWith('.test.ts') ? [path] : []
  })
}

const SRC = join(__dirname, '..')

describe('translations', () => {
  it('Arabic and English define exactly the same keys', () => {
    expect(keys(en as Tree).sort()).toEqual(keys(ar as Tree).sort())
  })

  it('no translation is empty, and placeholders match across languages', () => {
    for (const key of keys(ar as Tree)) {
      const a = lookup(ar as Tree, key)!
      const e = lookup(en as Tree, key)!
      expect(a.trim(), key).not.toBe('')
      expect(e.trim(), key).not.toBe('')
      const placeholders = (s: string) => [...s.matchAll(/{{\s*(\w+)\s*}}/g)].map((m) => m[1]).sort()
      expect(placeholders(e), key).toEqual(placeholders(a))
    }
  })

  it('every static t("...") key used in the code exists', () => {
    const missing: string[] = []
    for (const file of sourceFiles(SRC)) {
      for (const match of readFileSync(file, 'utf8').matchAll(/\bt\(\s*'([a-zA-Z0-9_.]+)'/g)) {
        if (!lookup(ar as Tree, match[1])) missing.push(`${file}: ${match[1]}`)
      }
    }
    expect(missing).toEqual([])
  })

  it('every dynamic key family used in the code is complete', () => {
    const roles = ['admin', 'author', 'reviewer', 'approver', 'pending']
    for (const role of roles) expect(lookup(ar as Tree, `roles.${role}`), role).toBeDefined()
    for (const code of ['invalid_credentials', 'throttled', 'network', 'not_found', 'permission_denied', 'validation_error', 'unknown']) {
      expect(lookup(ar as Tree, `errors.${code}`), code).toBeDefined()
    }
  })

  it('every rule the live document enforces has a translated error', () => {
    const shared = readFileSync(join(SRC, '..', '..', 'shared', 'src', 'operations.ts'), 'utf8')
    const codes = [...shared.matchAll(/DocumentRuleError\(\s*'([a-z_]+)'/g)].map((m) => m[1])
    expect(codes.length).toBeGreaterThan(5)
    for (const code of codes) expect(lookup(ar as Tree, `errors.${code}`), code).toBeDefined()
  })

  it('every reason and confidence an AI suggestion shows has a translation', () => {
    for (const reason of ['default', 'rules_only', 'not_released', 'not_configured', 'quota_exceeded']) {
      expect(lookup(ar as Tree, `suggestions.failed.${reason}`), reason).toBeDefined()
    }
    for (const level of ['high', 'medium', 'low']) expect(lookup(ar as Tree, `suggestions.confidence.${level}`), level).toBeDefined()
    for (const reason of ['default', 'rules_only', 'not_released', 'not_configured', 'quota_exceeded', 'too_long', 'ai_rejected']) {
      expect(lookup(ar as Tree, `suggestions.importFallback.${reason}`), reason).toBeDefined()
    }
    expect(lookup(ar as Tree, 'suggestions.warnings.NO_UNITS_DETECTED')).toBeDefined()
  })

  it('every reason a live save can fail for has a translated explanation', () => {
    for (const code of SAVE_ERROR_CODES) expect(lookup(ar as Tree, `live.saveErrors.${code}`), code).toBeDefined()
  })
})

// Attributes a user can see or hear; any string literal in them must come from t().
const VISIBLE_ATTRIBUTES = new Set(['placeholder', 'title', 'aria-label', 'alt', 'label'])
const HAS_LETTER = /\p{L}/u

function visit(node: unknown, onNode: (node: Record<string, unknown>) => void) {
  if (!node || typeof node !== 'object') return
  if (Array.isArray(node)) return node.forEach((child) => visit(child, onNode))
  const record = node as Record<string, unknown>
  if (typeof record.type === 'string') onNode(record)
  for (const value of Object.values(record)) if (value && typeof value === 'object') visit(value, onNode)
}

function hardCodedText(file: string): string[] {
  const found: string[] = []
  const ast = parseAst(readFileSync(file, 'utf8'), { lang: 'tsx' }, file)
  visit(ast, (node) => {
    if (node.type === 'JSXText' && HAS_LETTER.test(String(node.value))) found.push(`text "${String(node.value).trim()}"`)
    if (node.type === 'JSXAttribute') {
      const name = (node.name as { name?: string }).name ?? ''
      const value = node.value as { type?: string; value?: unknown } | null
      if (VISIBLE_ATTRIBUTES.has(name) && value?.type === 'Literal' && HAS_LETTER.test(String(value.value))) {
        found.push(`${name}="${String(value.value)}"`)
      }
    }
  })
  return found.map((entry) => `${file}: ${entry}`)
}

describe('no hard-coded user-visible text', () => {
  it('JSX text and visible attributes come from the translation system', () => {
    const offenders = sourceFiles(SRC)
      .filter((f) => f.endsWith('.tsx'))
      .flatMap(hardCodedText)
    expect(offenders).toEqual([])
  })

  it('the guard itself catches hard-coded text', async () => {
    const { mkdtempSync, writeFileSync } = await import('node:fs')
    const { tmpdir } = await import('node:os')
    const dir = mkdtempSync(join(tmpdir(), 'harak-guard-'))
    const file = join(dir, 'Bad.tsx')
    writeFileSync(file, 'export const Bad = () => <p title="Hello">مرحبا {name}</p>\nconst ok = <i>{t("x")}</i>\n')
    expect(hardCodedText(file).map((e) => e.split(': ')[1]).sort()).toEqual(['text "مرحبا"', 'title="Hello"'].sort())
  })
})
