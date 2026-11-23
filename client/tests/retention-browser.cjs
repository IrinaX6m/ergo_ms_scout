const assert = require('node:assert/strict'),
  path = require('node:path')
const { pathToFileURL } = require('node:url')
module.exports = async (browser, output) => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } }),
    errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  const url =
    pathToFileURL(path.join(output, 'fixture.html')).href +
    '#/scout/storage?job=11111111-1111-4111-8111-111111111111&run=22222222-2222-4222-8222-222222222222'
  const policy = () =>
    page.getByRole('heading', { name: 'Сроки хранения', exact: true }).locator('..')
  const section = (name) => page.getByRole('heading', { name, exact: true }).locator('..')
  const preview = () => section('Что затронет очистка')
  const deletion = () =>
    page.getByRole('button', { name: 'Подтвердить очистку этого перечня', exact: true })
  async function create() {
    await page
      .getByRole('button', { name: 'Рассчитать предварительный просмотр', exact: true })
      .click()
    await page.getByRole('heading', { name: 'Что затронет очистка', exact: true }).waitFor()
  }
  async function approve() {
    await page
      .getByRole('checkbox', {
        name: 'Я проверил перечень и понимаю потерю указанных данных',
        exact: true,
      })
      .check()
    await deletion().click()
    await page.getByRole('button', { name: 'Удалить указанные данные', exact: true }).click()
  }
  const mutations = () =>
    page.evaluate(() => window.__scoutTest.retention.calls.filter((c) => c[0] !== 'GET'))
  try {
    await page.goto(url)
    await page
      .getByRole('button', { name: 'Рассчитать предварительный просмотр', exact: true })
      .waitFor()
    assert.equal((await mutations()).length, 0)
    const html = policy().getByLabel('HTML страниц', { exact: true }),
      result = policy().getByLabel('Результаты и Evidence', { exact: true })
    await html.fill('0')
    assert(
      await policy().getByRole('button', { name: 'Сохранить сроки', exact: true }).isDisabled(),
    )
    await html.fill('45')
    await result.fill('30')
    assert(
      await policy().getByRole('button', { name: 'Сохранить сроки', exact: true }).isDisabled(),
    )
    await page.getByRole('link', { name: 'Вернуться к Scout', exact: true }).click()
    await page.getByRole('button', { name: 'Отмена', exact: true }).click()
    assert.equal(await html.inputValue(), '45')
    await result.fill('365')
    await page.evaluate(() => (window.__scoutTest.retention.policyConflict = true))
    await policy().getByRole('button', { name: 'Сохранить сроки', exact: true }).click()
    await policy().getByRole('button', { name: 'Оставить мои правки', exact: true }).waitFor()
    assert.equal(await html.inputValue(), '45')
    await policy().getByRole('button', { name: 'Оставить мои правки', exact: true }).click()
    await policy().getByRole('button', { name: 'Сохранить сроки', exact: true }).click()
    await page.getByText('Политика подтверждена сервером.', { exact: true }).waitFor()
    assert.equal(await page.evaluate(() => window.__scoutTest.retention.policy.version), 3)
    await policy()
      .getByRole('checkbox', { name: /Не удалять по возрасту.*HTML страниц/ })
      .check()
    await policy().getByRole('button', { name: 'Сохранить сроки', exact: true }).click()
    await page.waitForFunction(() => window.__scoutTest.retention.policy.html_days === null)
    await policy()
      .getByRole('checkbox', {
        name: 'Разрешить автоматическую очистку по этим срокам',
        exact: true,
      })
      .check()
    const before = (await mutations()).length
    await policy().getByRole('button', { name: 'Сохранить сроки', exact: true }).click()
    await page.getByRole('button', { name: 'Отмена', exact: true }).click()
    assert.equal((await mutations()).length, before)
    assert.equal(
      await page.evaluate(() => window.__scoutTest.retention.policy.automatic_enabled),
      false,
    )
    await policy().getByRole('button', { name: 'Обновить политику', exact: true }).click()
    await policy()
      .getByRole('button', { name: 'Взять значения сервера', exact: true })
      .count()
      .then(async (count) => {
        if (count)
          await policy()
            .getByRole('button', { name: 'Взять значения сервера', exact: true })
            .click()
      })
    // Reload preserves unsaved input; restore it explicitly before preparing a manifest.
    await policy()
      .getByRole('checkbox', {
        name: 'Разрешить автоматическую очистку по этим срокам',
        exact: true,
      })
      .uncheck()
    const run = section('Защита открытого результата')
    await run.getByRole('button', { name: 'Закрепить результат', exact: true }).click()
    await page.waitForFunction(() => window.__scoutTest.retention.hold.scope === 'results')
    let call = (await mutations()).at(-1)
    assert.equal(call[0], 'PUT')
    assert(call[3].headers['Idempotency-Key'])
    assert.deepEqual(call[2], { expected_version: 1, scope: 'results' })
    await run.getByRole('button', { name: 'Снять закрепление', exact: true }).click()
    await page.getByRole('button', { name: 'Снять закрепление', exact: true }).last().click()
    await page.waitForFunction(() => window.__scoutTest.retention.hold.scope === null)
    call = (await mutations()).at(-1)
    assert.equal(call[0], 'DELETE')
    assert.deepEqual(call[3].data, { expected_version: 2 })
    assert(call[3].headers['Idempotency-Key'])
    await page.evaluate(() => (window.__scoutTest.retention.unknownHold = true))
    await run.getByRole('button', { name: 'Закрепить со всеми материалами', exact: true }).click()
    await run
      .getByRole('button', { name: 'Повторить тот же запрос закрепления', exact: true })
      .waitFor()
    const holdKey = (await mutations()).filter((c) => c[0] === 'PUT').at(-1)[3].headers[
      'Idempotency-Key'
    ]
    await run
      .getByRole('button', { name: 'Повторить тот же запрос закрепления', exact: true })
      .click()
    await run
      .getByText('Некоторые материалы уже недоступны; закрепление их не восстановит.', {
        exact: false,
      })
      .waitFor()
    assert.equal(
      (await mutations()).filter((c) => c[0] === 'PUT').at(-1)[3].headers['Idempotency-Key'],
      holdKey,
    )
    await page.getByRole('checkbox', { name: 'Комплекты результата', exact: true }).check()
    await create()
    await preview()
      .getByText('Один из последних защищённых результатов', { exact: true })
      .first()
      .waitFor()
    assert(await deletion().isDisabled())
    assert((await preview().innerText()).includes('Неизвестно'))
    assert((await preview().innerText()).includes('сравнение'))
    await preview().getByRole('button', { name: 'Загрузить следующую порцию', exact: true }).click()
    await preview()
      .getByText('Общий файл защищён другими ссылками', { exact: true })
      .last()
      .waitFor()
    await preview()
      .getByRole('checkbox', {
        name: 'Я проверил перечень и понимаю потерю указанных данных',
        exact: true,
      })
      .check()
    const writesBefore = (await mutations()).filter(
      (c) => c[1] === 'scout/retention/cleanups/',
    ).length
    await deletion().click()
    await page.getByRole('button', { name: 'Отмена', exact: true }).click()
    assert.equal(
      (await mutations()).filter((c) => c[1] === 'scout/retention/cleanups/').length,
      writesBefore,
    )
    // Any scope edit discards the old immutable manifest and its consent.
    await page.getByRole('checkbox', { name: 'Файлы выгрузок', exact: true }).uncheck()
    assert.equal(
      await page.getByRole('heading', { name: 'Что затронет очистка', exact: true }).count(),
      0,
    )
    await page.evaluate(() => (window.__scoutTest.retention.notExecutable = true))
    await create()
    assert(await deletion().isDisabled())
    assert((await preview().innerText()).includes('объём не подтверждён'))
    await page.evaluate(() => {
      window.__scoutTest.retention.notExecutable = false
      window.__scoutTest.retention.expire = true
    })
    await create()
    await page
      .getByText('Срок просмотра истёк. Рассчитайте новый перечень.', { exact: true })
      .waitFor()
    assert(await deletion().isDisabled())
    await page.evaluate(() => {
      window.__scoutTest.retention.expire = false
      window.__scoutTest.retention.previewConflict = true
    })
    await create()
    await approve()
    await page
      .getByText('Перечень или защита изменились; нужен новый просмотр.', { exact: true })
      .waitFor()
    assert.equal(await deletion().count(), 0)
    // A lost response reuses exactly the same manifest/hash/key after a full reload.
    await create()
    await page.evaluate(() => (window.__scoutTest.retention.unknown = true))
    await approve()
    await page
      .getByRole('button', { name: 'Повторить тот же запрос очистки', exact: true })
      .waitFor()
    const first = (await mutations()).filter((c) => c[1] === 'scout/retention/cleanups/').at(-1)[2]
    await page.getByRole('button', { name: 'Повторить тот же запрос очистки', exact: true }).click()
    await page.getByRole('heading', { name: /Операция очистки/ }).waitFor()
    const second = (await mutations()).filter((c) => c[1] === 'scout/retention/cleanups/').at(-1)[2]
    assert.deepEqual(second, first)
    await page.evaluate(() => (window.__scoutTest.retention.cleanupDone = true))
    await page.getByRole('button', { name: 'Обновить состояние операции', exact: true }).click()
    await page.getByRole('heading', { name: 'Операция очистки · Завершена', exact: true }).waitFor()
    assert((await section('Операция очистки · Завершена').innerText()).includes('60'))
    // Test the saved exact request on a real browser reload without executing an unknown new request.
    await page.evaluate(
      (body) =>
        sessionStorage.setItem(
          'scout.retention.pending-cleanup:' +
            JSON.stringify([
              '11111111-1111-4111-8111-111111111111',
              '22222222-2222-4222-8222-222222222222',
            ]),
          JSON.stringify({
            context: JSON.stringify([
              '11111111-1111-4111-8111-111111111111',
              '22222222-2222-4222-8222-222222222222',
            ]),
            body,
          }),
        ),
      first,
    )
    await page.goto(url)
    await page.reload()
    await page
      .getByRole('button', { name: 'Повторить тот же запрос очистки', exact: true })
      .waitFor()
    assert(
      await page
        .getByRole('button', { name: 'Рассчитать предварительный просмотр', exact: true })
        .isDisabled(),
    )
    await page.evaluate(() => sessionStorage.clear())
    await page.reload()
    // Read permission failure must not expose an editable default policy.
    await page.evaluate(() => (window.__scoutTest.retention.error = 403))
    await policy().getByRole('button', { name: 'Обновить политику', exact: true }).click()
    await policy().getByText('Недостаточно прав для этой операции.', { exact: true }).waitFor()
    assert(
      await policy().getByRole('button', { name: 'Сохранить сроки', exact: true }).isDisabled(),
    )
    await page.evaluate(() => (window.__scoutTest.retention.error = 0))
    await policy().getByRole('button', { name: 'Обновить политику', exact: true }).click()
    // Delayed preview for a previous context cannot replace the new job's screen.
    await page.evaluate(() => (window.__scoutTest.retention.defer = true))
    await page
      .getByRole('button', { name: 'Рассчитать предварительный просмотр', exact: true })
      .click()
    await page.waitForFunction(() => window.__scoutTest.retention.release)
    await page.evaluate(
      () => (location.hash = '/scout/storage?job=33333333-3333-4333-8333-333333333333'),
    )
    await page
      .getByRole('button', { name: 'Рассчитать предварительный просмотр', exact: true })
      .waitFor()
    await page.evaluate(() => window.__scoutTest.retention.release())
    await page.waitForTimeout(50)
    assert.equal(await deletion().count(), 0)
    await page.getByRole('radio', { name: 'Все мои задания', exact: true }).check()
    await page.getByRole('checkbox', { name: 'Временные снимки настройки', exact: true }).check()
    await create()
    const body = (await mutations()).filter((c) => c[1] === 'scout/retention/previews/').at(-1)[2]
    assert.equal('job_public_id' in body, false)
    assert(body.scopes.includes('visual_snapshots'))
    for (const theme of ['light', 'dark']) {
      await page.evaluate(
        (value) => document.documentElement.setAttribute('data-theme', value),
        theme,
      )
      for (const width of [1440, 768, 360, 320]) {
        await page.setViewportSize({ width, height: 1100 })
        const box = await page
          .locator('main')
          .evaluate((e) => ({ width: e.clientWidth, scroll: e.scrollWidth }))
        assert(
          box.scroll <= box.width + 2,
          `Retention overflow ${theme}/${width}: ${JSON.stringify(box)}`,
        )
      }
      await page.screenshot({
        path: path.join(output, `retention-${theme}-mobile.png`),
        fullPage: true,
      })
    }
    assert.deepEqual(errors, [])
    console.log(
      'Retention UI passed: versioned policy, null/validation, consent/cancel, headered holds, immutable preview, expiry, protected/unknown sizes, cursor, exact retry, cleanup status, permissions, late response and themes',
    )
  } finally {
    await page.close()
  }
}
