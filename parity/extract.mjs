#!/usr/bin/env node
/**
 * Harak 1 parity extraction (phase 4, task 4.1).
 *
 * Loads Harak 1 (a single offline HTML file) in headless Chromium with the
 * network off, checks it is exactly the file pinned in harak1.lock.json, and
 * calls Harak 1's own pure rule functions on the fixed corpus. The results go
 * to expected/*.json, one item per line, with the inputs alongside, so the
 * Python port can be tested against them without Harak 1 present.
 *
 * Harak 1 is never modified: it is read from disk and run in a browser page.
 *
 *   HARAK1_HTML=/path/to/curriculum-analyzer.html node extract.mjs            write expected/
 *   HARAK1_HTML=/path/to/curriculum-analyzer.html node extract.mjs --check    extract again and compare byte for byte
 */
import { chromium } from '@playwright/test'
import { createHash } from 'node:crypto'
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const check = process.argv.includes('--check')
const expectedDir = join(here, 'expected')

function fail(message) {
  console.error(`parity: ${message}`)
  process.exit(1)
}

const htmlPath = process.env.HARAK1_HTML
if (!htmlPath) fail('set HARAK1_HTML to the path of Harak 1 (curriculum-analyzer.html)')
const lock = JSON.parse(readFileSync(join(here, 'harak1.lock.json'), 'utf8'))
const html = readFileSync(htmlPath)
const sha256 = createHash('sha256').update(html).digest('hex')
if (sha256 !== lock.sha256) fail(`${htmlPath} has SHA-256 ${sha256}, expected ${lock.sha256}; refusing to record results from a different Harak 1`)

/** Deterministic pseudo-random numbers (mulberry32). */
function random(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const range = (from, to) => Array.from({ length: to - from + 1 }, (_, i) => String.fromCodePoint(from + i))
const POOLS = [
  { weight: 30, chars: range(0x0621, 0x064a) },
  { weight: 6, chars: [...range(0x064b, 0x065f), 'ٰ', ...range(0x0610, 0x061a), ...range(0x06d6, 0x06ed), 'ـ'] },
  { weight: 4, chars: ['أ', 'إ', 'آ', 'ء', 'ؤ', 'ئ', 'ة', 'ى', 'ٱ'] },
  { weight: 2, chars: ['پ', 'چ', 'ک', 'گ', 'ی', 'ہ', 'ے'] },
  { weight: 2, chars: ['ﺍ', 'ﻻ', 'ﻷ', 'ﭖ', 'ﷲ', 'ﺀ', 'ﻠ', 'ﺔ'] },
  { weight: 4, chars: [...range(0x30, 0x39), ...range(0x0660, 0x0669), ...range(0x06f0, 0x06f9)] },
  { weight: 3, chars: [...range(0x41, 0x5a), ...range(0x61, 0x7a)] },
  { weight: 14, chars: [' ', ' ', ' ', '\t', ' ', ' ', '‏', '‎', '‌', '‍', '\n', '\r\n', '\r', '　', ' ', ' ', '\u0085', '\u001c', '᠎', '﻿'] },
  { weight: 5, chars: ['.', '،', '؛', '؟', ':', '-', '–', '—', ')', '(', '%', '٪', '«', '»', '"', '/', '!'] },
  { weight: 1, chars: ['😀', '🇴🇲', '𝒜'] },
  { weight: 8, chars: ['ال', 'وال', 'بال', 'فال', 'كال', 'لل', 'أن ', 'ان ', 'يذكر', 'تحدد', 'المتدرب', 'ها', 'ون', 'كما', 'دد', 'لا'] },
]
const TOTAL = POOLS.reduce((n, p) => n + p.weight, 0)

function fuzzTexts(count, seed) {
  const next = random(seed)
  const out = []
  for (let i = 0; i < count; i += 1) {
    const length = Math.floor(next() * 40)
    let text = ''
    for (let j = 0; j < length; j += 1) {
      let roll = next() * TOTAL
      const pool = POOLS.find((p) => (roll -= p.weight) < 0) ?? POOLS[0]
      text += pool.chars[Math.floor(next() * pool.chars.length)]
    }
    out.push(text)
  }
  return out
}

/** Variants of every dictionary verb, so each entry and each lookup path is exercised. */
function verbVariants(verbs) {
  const out = []
  for (const verb of verbs) {
    const t = `ت${verb.slice(1)}`
    out.push(
      `أن ${verb} المتدرب الإجراء المطلوب.`,
      `${verb} المتدرب الإجراء.`,
      `أن ${t} المتدربة الإجراء.`,
      `أن ${verb}ها المتدرب في الموقع.`,
      `أن ${verb}ون الإجراء.`,
      `أن ${verb[0]}َ${verb[1]}ّ${verb.slice(2)} المتدرب الإجراء بدقة.`,
      `أن ${verb.slice(0, 2)}دد${verb.slice(2)} المتدرب الإجراء.`,
      `١. أن ${verb.replace('ا', 'أ')} المتدرب الإجراء ثم يشرح النتيجة.`,
    )
  }
  return [...new Set(out)]
}

const writeLines = (dir, name, items) =>
  writeFileSync(join(dir, name), `[\n${items.map((item) => JSON.stringify(item)).join(',\n')}\n]\n`)
const writeJson = (dir, name, value) => writeFileSync(join(dir, name), `${JSON.stringify(value, null, 2)}\n`)

async function extract(outDir) {
  // Same browser lookup as the e2e tests: PW_CHROMIUM_PATH, then the preinstalled Chromium, then Playwright's own.
  const localChromium = '/opt/pw-browsers/chromium'
  const executablePath = process.env.PW_CHROMIUM_PATH ?? (existsSync(localChromium) ? localChromium : undefined)
  const browser = await chromium.launch(executablePath ? { executablePath } : {})
  const context = await browser.newContext({ offline: true })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto(pathToFileURL(htmlPath).href)
  await page.waitForFunction(() => typeof classifyBloom === 'function' && typeof structure === 'function')

  const re = (r) => ({ source: r.source, flags: r.flags })
  const data = await page.evaluate(() => {
    const re = (r) => (r ? { source: r.source, flags: r.flags } : null)
    const fw = (id) => RULES.frameworks.find((f) => f.id === id)
    const domain = (d) => RULES.frameworks.find((f) => f.kind === 'taxonomy' && f.domain === d)
    return {
      appVersion: APP_VERSION,
      bloomLevels: RULES.bloomLevels,
      pronounSuffixes: PRONOUN_SUFFIXES,
      verbSuffixes: VERB_SUFFIXES,
      stopWords: RULES.stopWords,
      tashkeel: re(TASHKEEL),
      matchThresholds: MATCH_THRESHOLDS,
      domainNames: DOMAIN_NAMES,
      affective: { id: domain('affective').id, levels: domain('affective').levels.map((l) => ({ id: l.id, name: l.name, verbs: l.verbs || [] })) },
      psychomotor: { id: domain('psychomotor').id, levels: domain('psychomotor').levels.map((l) => ({ id: l.id, name: l.name, verbs: l.verbs || [] })) },
      dimensions: fw('bloom-revised').dimensions.map((d) => ({ id: d.id, name: d.name, keywords: d.keywords })),
      qualityPatterns: Object.fromEntries(Object.entries(QUALITY_PATTERNS).map(([k, v]) => [k, Array.isArray(v) ? v : re(v)])),
      structurePatterns: RULES.structurePatterns.map((p) => ({ type: p.type, heading: re(p.heading), item: re(p.item), numbered: !!p.numbered })),
      objectiveLine: re(RULES.objectiveLine),
      objectiveLineLoose: re(RULES.objectiveLineLoose),
      reader: Object.fromEntries(Object.entries(READER).map(([k, v]) => [k, v instanceof RegExp ? re(v) : v])),
      samples: { sample: SAMPLE_CURRICULUM, normal: NORMAL_TXT },
    }
  })
  void re

  const corpus = JSON.parse(readFileSync(join(here, 'corpus', 'objectives.json'), 'utf8')).items
  const competencies = JSON.parse(readFileSync(join(here, 'corpus', 'competencies.json'), 'utf8')).items
  const edge = JSON.parse(readFileSync(join(here, 'corpus', 'edge-cases.json'), 'utf8'))
  const dictionary = [
    ...data.bloomLevels.flatMap((l) => l.verbs),
    ...data.affective.levels.flatMap((l) => l.verbs.map((v) => v.split(' ')[0])),
    ...data.psychomotor.levels.flatMap((l) => l.verbs.map((v) => v.split(' ')[0])),
  ]
  const objectives = [...new Set([...corpus, ...edge.objectives, ...verbVariants([...new Set(dictionary)])])]
  const texts = [...new Set([...fuzzTexts(400, 20261003), ...edge.texts, ...corpus, ...edge.objectives, ...competencies.map((c) => c.text)])]

  const textResults = await page.evaluate(
    (texts) =>
      texts.map((input) => ({
        input,
        stripTashkeel: stripTashkeel(input),
        unifyHamza: unifyHamza(input),
        normalizeArabic: normalizeArabic(input),
        tokenSet: [...tokenSet(input)],
        countWords: countWords(input),
        normalizeText: normalizeText(input),
        countArabicChars: countArabicChars(input),
        reverseLines: reverseLines(input),
        detectReversed: detectReversed(input),
      })),
    texts,
  )

  const objectiveResults = await page.evaluate((objectives) => {
    const struct = mkStruct(objectives)
    const bloom = classifyBloom(struct)
    const quality = checkObjectives(struct, bloom)
    return objectives.map((input, i) => {
      const verb = extractVerb(input)
      const b = bloom[i]
      const q = quality[i]
      return {
        input,
        verb,
        lookupVerb: verb ? lookupVerb(verb) : null,
        lookupDomainVerb: verb ? lookupDomainVerb(verb) : null,
        bloom: { verb: b.verb, level: b.level, levelId: b.levelId, domain: b.domain, confidence: b.confidence },
        objectiveBody: objectiveBody(input),
        quality: { components: q.components, score: q.score, errors: q.errors, dimension: q.dimension },
        dimensionOfBody: guessDimension(objectiveBody(input)),
      }
    })
  }, objectives)

  const matching = await page.evaluate(
    ({ objectives, competencies }) => {
      const standards = competencies.map((c, i) => ({ id: c.code || `c${i}`, code: c.code, text: c.text }))
      const standardTexts = standards.map((s) => [s.code, s.text].filter(Boolean).join(' '))
      const pairs = []
      objectives.forEach((objective, oi) => {
        const a = tokenSet(objective)
        standardTexts.forEach((text, si) => {
          const score = jaccard(a, tokenSet(text))
          pairs.push({ objective: oi, standard: si, score, rounded: Math.round(score * 100) / 100, confidence: scoreConfidence(score) })
        })
      })
      const matches = matchStandards(mkStruct(objectives), standards, [])
        .filter((m) => m.source === 'user')
        .map((m) => ({ objective: m.objectiveRef.index, standardId: m.standardId, standardText: m.standardText, score: m.score, confidence: m.confidence }))
      return { objectives, standards, standardTokens: standardTexts.map((t) => [...tokenSet(t)]), pairs, matches }
    },
    { objectives: corpus, competencies },
  )

  const edgePairs = await page.evaluate(
    (pairs) =>
      pairs.map(({ note, objective, competency }) => {
        const score = jaccard(tokenSet(objective), tokenSet(competency))
        const matches = matchStandards(mkStruct([objective]), [{ id: 'X', code: '', text: competency }], [])
          .filter((m) => m.source === 'user')
          .map((m) => ({ score: m.score, confidence: m.confidence }))
        return { note, objective, competency, score, rounded: Math.round(score * 100) / 100, confidence: scoreConfidence(score), matches }
      }),
    edge.pairs,
  )

  const files = readdirSync(join(here, 'corpus', 'curricula')).filter((f) => f.endsWith('.txt')).sort()
  const curricula = [
    ...files.map((f) => ({ name: f, text: readFileSync(join(here, 'corpus', 'curricula', f), 'utf8') })),
    { name: 'harak1:sample', text: data.samples.sample },
    { name: 'harak1:normal', text: data.samples.normal },
    { name: 'harak1:normal-reversed', text: data.samples.normal.split('\n').map((l) => Array.from(l).reverse().join('')).join('\n') },
    { name: 'long', text: Array(4).fill(readFileSync(join(here, 'corpus', 'curricula', 'safety-program.txt'), 'utf8')).join('\n') },
    { name: 'empty', text: '' },
    { name: 'latin-only', text: 'Unit 1: Safety\nLesson 1: Hazards\nObjectives:\nList the hazards.' },
  ]
  const documents = await page.evaluate(async (curricula) => {
    const out = []
    for (const { name, text } of curricula) {
      try {
        const doc = await readDocument(new File([text], `${name}.txt`, { type: 'text/plain' }))
        delete doc.meta.readAt
        const struct = structure(doc)
        const bloom = classifyBloom(struct)
        const { completeness, stats } = summarize(struct, bloom, doc)
        const quality = checkObjectives(struct, bloom)
        out.push({ name, input: text, document: doc, structure: struct, bloom, completeness, stats, quality, taxonomyMatrix: taxonomyMatrix(bloom, quality) })
      } catch (error) {
        out.push({ name, input: text, error: error.code ?? String(error) })
      }
    }
    return out
  }, curricula)

  const pagination = await page.evaluate(
    (texts) => texts.map((input) => ({ input, pages: paginateText(input), pages100: paginateText(input, 100) })),
    curricula.map((c) => c.text),
  )

  if (errors.length) throw new Error(`Harak 1 raised errors: ${errors.join('; ')}`)
  const chromiumVersion = browser.version()
  await browser.close()

  delete data.samples
  writeJson(outDir, 'meta.json', { harak1: lock, chromium: chromiumVersion, counts: { texts: texts.length, objectives: objectives.length, pairs: matching.pairs.length, edgePairs: edgePairs.length, documents: documents.length } })
  writeJson(outDir, 'data.json', data)
  writeLines(outDir, 'text.json', textResults)
  writeLines(outDir, 'objectives.json', objectiveResults)
  writeJson(outDir, 'matching.json', { ...matching, pairs: undefined })
  writeLines(outDir, 'matching-pairs.json', matching.pairs)
  writeLines(outDir, 'matching-edge.json', edgePairs)
  writeLines(outDir, 'documents.json', documents)
  writeLines(outDir, 'pagination.json', pagination)
}

if (check) {
  const temp = mkdtempSync(join(tmpdir(), 'harak2-parity-'))
  try {
    await extract(temp)
    const names = readdirSync(temp).sort()
    const committed = readdirSync(expectedDir).filter((f) => f.endsWith('.json')).sort()
    if (JSON.stringify(names) !== JSON.stringify(committed)) fail(`files differ: ${names} vs ${committed}`)
    for (const name of names) {
      if (!readFileSync(join(temp, name)).equals(readFileSync(join(expectedDir, name)))) fail(`${name} differs from the committed expected output`)
    }
    console.log(`parity: ${names.length} files identical to expected/`)
  } finally {
    rmSync(temp, { recursive: true, force: true })
  }
} else {
  await extract(expectedDir)
  console.log('parity: expected/ written')
}
