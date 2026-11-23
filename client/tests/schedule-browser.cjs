const assert = require('node:assert/strict')
const path = require('node:path')
const { pathToFileURL } = require('node:url')
module.exports = async (browser, output) => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } }),
    errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  try {
    const url = pathToFileURL(path.join(output, 'fixture.html')).href + '#/schedule-test'
    await page.goto(url)
    const panel = page.locator('.scout-schedule')
    await panel.locator('summary').first().click()
    await panel.getByText('Расписание ещё не создано.', { exact: true }).waitFor()
    const create = panel.getByRole('button', { name: 'Создать расписание', exact: true })
    const time = panel.getByLabel('Время каждый день', { exact: true }),
      zone = panel.getByLabel('Часовой пояс', { exact: true })
    await time.fill('09:00')
    await zone.fill('Europe/Moscow')
    await page.evaluate(() => (window.__scoutTest.schedule.context.plan.approved = false))
    assert(await create.isDisabled())
    await page.evaluate(() => (window.__scoutTest.schedule.context.plan.approved = true))
    await page.evaluate(() => (window.__scoutTest.schedule.context.planDirty = true))
    assert(await create.isDisabled())
    await page.evaluate(() => (window.__scoutTest.schedule.context.planDirty = false))
    await panel.getByRole('checkbox').check()
    await create.click()
    await page.getByRole('button', { name: 'Отмена', exact: true }).click()
    assert.equal(
      await page.evaluate(
        () => window.__scoutTest.schedule.calls.filter((c) => c[0] !== 'get').length,
      ),
      0,
    )
    await create.click()
    await page.getByRole('button', { name: 'Разрешить и сохранить', exact: true }).click()
    await panel.getByText('Настройки подтверждены сервером.', { exact: true }).waitFor()
    let calls = await page.evaluate(() => window.__scoutTest.schedule.calls)
    assert.deepEqual(calls.find((c) => c[0] === 'post')[2], {
      local_time: '09:00',
      timezone: 'Europe/Moscow',
      enabled: true,
      plan_revision_public_id: 'revision-one',
      plan_hash: 'hash-one',
    })
    await panel.getByText(/Другой сбор занимал общий слот/).waitFor()
    await panel.getByRole('button', { name: 'Загрузить следующие дни', exact: true }).click()
    await panel.getByText(/Такого местного времени нет из-за перевода часов/).waitFor()
    assert.equal(await panel.locator('.scout-schedule-days > li').count(), 2)
    assert(
      (await panel.getByRole('link', { name: 'Открыть запуск' }).getAttribute('href')).includes(
        'run=run-history',
      ),
    )
    await time.fill('10:00')
    await panel.getByRole('button', { name: 'Выключить будущие запуски', exact: true }).click()
    await panel
      .getByText('Для выключенного расписания следующий запуск не назначен.', { exact: true })
      .waitFor()
    assert.equal(await time.inputValue(), '10:00')
    calls = await page.evaluate(() => window.__scoutTest.schedule.calls)
    assert.deepEqual(calls.filter((c) => c[0] === 'patch').at(-1)[2], {
      expected_version: 1,
      enabled: false,
    })
    // Ordinary edits keep the old revision; explicit rebind adopts the newly approved plan.
    await page.evaluate(() =>
      Object.assign(window.__scoutTest.schedule.context.plan, {
        public_id: 'revision-two',
        plan_hash: 'hash-two',
        revision_number: 2,
      }),
    )
    await panel.getByRole('button', { name: 'Сохранить расписание', exact: true }).click()
    await panel.getByText('Настройки подтверждены сервером.', { exact: true }).waitFor()
    assert.equal(
      await page.evaluate(() => window.__scoutTest.schedule.current.plan_hash),
      'hash-one',
    )
    await panel
      .getByRole('button', { name: 'Сохранить с текущим подтверждённым планом', exact: true })
      .click()
    await page.waitForFunction(() => window.__scoutTest.schedule.current.plan_hash === 'hash-two')
    // A stale version must not overwrite another editor or erase local input.
    await page.evaluate(() => (window.__scoutTest.schedule.conflict = true))
    await time.fill('11:00')
    await panel.getByRole('button', { name: 'Сохранить расписание', exact: true }).click()
    await panel
      .getByRole('button', { name: 'Оставить мои правки для сохранения', exact: true })
      .waitFor()
    assert.equal(await time.inputValue(), '11:00')
    assert(
      await panel.getByRole('button', { name: 'Сохранить расписание', exact: true }).isDisabled(),
    )
    await panel
      .getByRole('button', { name: 'Оставить мои правки для сохранения', exact: true })
      .click()
    await panel.getByRole('button', { name: 'Сохранить расписание', exact: true }).click()
    await page.waitForFunction(() => window.__scoutTest.schedule.current.local_time === '11:00')
    assert.equal(
      await page.evaluate(
        () =>
          window.__scoutTest.schedule.calls.filter((c) => c[0] === 'patch').at(-1)[2]
            .expected_version,
      ),
      5,
    )
    // A lost POST response is reconciled by GET, never blindly submitted twice.
    await page.reload()
    await panel.locator('summary').first().click()
    await panel.getByText('Расписание ещё не создано.', { exact: true }).waitFor()
    await zone.fill('Europe/Moscow')
    await page.evaluate(() => (window.__scoutTest.schedule.unknown = true))
    await create.click()
    await panel.getByText('Настройки подтверждены сервером.', { exact: true }).waitFor()
    assert.equal(
      await page.evaluate(
        () => window.__scoutTest.schedule.calls.filter((c) => c[0] === 'post').length,
      ),
      1,
    )
    // Existing settings load into the form; a read error cannot be mistaken for an absent schedule.
    await page.evaluate(() => {
      window.__scoutTest.schedule.current.local_time = '15:30'
    })
    await panel.getByRole('button', { name: 'Обновить расписание', exact: true }).click()
    assert.equal(await time.inputValue(), '15:30')
    await page.evaluate(() => (window.__scoutTest.schedule.error = 403))
    await panel.getByRole('button', { name: 'Обновить расписание', exact: true }).click()
    await panel
      .getByText('Недостаточно прав для этой операции. Настройки не изменены.', { exact: true })
      .waitFor()
    assert(
      await panel.getByRole('button', { name: 'Сохранить расписание', exact: true }).isDisabled(),
    )
    await page.evaluate(() => (window.__scoutTest.schedule.error = 0))
    await panel.getByRole('button', { name: 'Обновить расписание', exact: true }).click()
    // Ignore a response captured for the previous job.
    await page.evaluate(() => {
      const s = window.__scoutTest.schedule
      s.defer = true
    })
    await panel.getByRole('button', { name: 'Обновить расписание', exact: true }).click()
    await page.waitForFunction(() => window.__scoutTest.schedule.release)
    await page.evaluate(() => {
      const s = window.__scoutTest.schedule
      s.current = null
      s.context.jobId = 'other-job'
    })
    await panel.getByText('Расписание ещё не создано.', { exact: true }).waitFor()
    await page.evaluate(() => window.__scoutTest.schedule.release())
    await page.waitForTimeout(100)
    assert.equal(
      await panel.getByRole('button', { name: 'Создать расписание', exact: true }).count(),
      1,
    )
    for (const theme of ['light', 'dark']) {
      await page.evaluate(
        (value) => document.documentElement.setAttribute('data-theme', value),
        theme,
      )
      for (const width of [1440, 768, 360, 320]) {
        await page.setViewportSize({ width, height: 1100 })
        const box = await panel.evaluate((e) => ({ width: e.clientWidth, scroll: e.scrollWidth }))
        assert(
          box.scroll <= box.width + 2,
          `schedule overflow ${theme}/${width}: ${JSON.stringify(box)}`,
        )
      }
      await page.screenshot({
        path: path.join(output, `schedule-${theme}-mobile.png`),
        fullPage: true,
      })
    }
    assert.deepEqual(errors, [])
    console.log(
      'Schedule UI: consent, approval, pinned revision, disable, history, conflicts, lost response, permissions, late response and themes passed',
    )
  } finally {
    await page.close()
  }
}
