const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

const root = path.resolve(__dirname, '../../../..')
const output = path.join(root, 'virtual_env/cache/tmp/scout-client-browser')
process.env.TEMP = path.join(root, 'virtual_env/cache/tmp')
process.env.TMP = process.env.TEMP

async function main() {
  // Keep generated core auto-import metadata in its normal build directory.
  process.chdir(path.join(root, 'core/client'))
  const { build } = await import(
    pathToFileURL(path.join(root, 'virtual_env/npm/node_modules/vite/dist/node/index.js')).href
  )
  await build({
    configFile: path.join(root, 'core/client/vite.config.js'),
    root: __dirname,
    base: './',
    build: {
      outDir: output,
      emptyOutDir: true,
      rolldownOptions: { input: path.join(__dirname, 'fixture.html') },
    },
  })
  const { chromium } = require(path.join(root, 'virtual_env/npm/node_modules/playwright'))
  const executablePath =
    process.env.ERGO_BROWSER_EXECUTABLE ||
    [
      'C:/Program Files/Google/Chrome/Application/chrome.exe',
      'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    ].find((file) => fs.existsSync(file))
  const browser = await chromium.launch({
    headless: true,
    ...(executablePath ? { executablePath } : {}),
    args: ['--allow-file-access-from-files'],
  })
  let page
  try {
    page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.goto(pathToFileURL(path.join(output, 'fixture.html')).href)
    const ui = page.locator('.scout-workflow')
    async function checkWidths(name) {
      for (const width of [1440, 768, 360, 320]) {
        await page.setViewportSize({ width, height: 1100 })
        const box = await ui.evaluate((element) => ({
          width: element.clientWidth,
          scroll: element.scrollWidth,
        }))
        assert.ok(
          box.scroll <= box.width + 2,
          `${name}: horizontal overflow at ${width}: ${JSON.stringify(box)}`,
        )
        if (width <= 360) {
          const rail = await ui.locator('.step-rail__list').evaluate((element) => ({
            width: element.clientWidth,
            scroll: element.scrollWidth,
          }))
          assert.ok(rail.scroll <= rail.width + 2, `${name}: hidden steps at ${width}`)
        }
      }
      await page.screenshot({ path: path.join(output, `${name}-mobile.png`), fullPage: true })
      await page.setViewportSize({ width: 1440, height: 1100 })
      await page.screenshot({ path: path.join(output, `${name}-desktop.png`), fullPage: true })
    }
    await ui.getByRole('heading', { name: 'Как подготовим задание?' }).waitFor()
    await checkWidths('modes')

    // Unsupported modes must not send made-up API requests, and must retain the source.
    await ui.locator('.scout-mode').nth(2).click()
    await ui.getByRole('button', { name: 'Далее: источник и правила' }).click()
    await ui.locator('#scout-mode-source').fill('https://events.example/list')
    await ui.locator('#scout-request').fill('Собери названия мероприятий')
    await ui.getByRole('button', { name: 'Перейти к ручным правилам' }).click()
    assert.equal(await ui.locator('#scout-url').inputValue(), 'https://events.example/list')
    assert.equal(await page.evaluate(() => window.__scoutTest.calls.length), 0)

    await ui.locator('#scout-name-0').fill('title')
    await ui.locator('#scout-selector-0').fill('.title')
    await checkWidths('source')
    await ui.getByRole('button', { name: 'Настройки системы', exact: true }).click()
    assert.equal(await page.evaluate(() => window.__scoutTest.systemOpened), 1)
    assert.equal(await ui.locator('#scout-selector-0').inputValue(), '.title')
    await ui.getByRole('button', { name: 'Получить предпросмотр', exact: true }).click()
    await ui.getByRole('heading', { name: 'Предпросмотр готов' }).waitFor()
    assert.equal(
      await page.evaluate(() =>
        window.__scoutTest.calls.some(
          ([method, url]) => method === 'post' && /\/(approve|start)\/$/.test(url),
        ),
      ),
      false,
    )
    await ui.getByRole('button', { name: 'К подтверждению', exact: true }).click()
    await ui.getByRole('heading', { name: 'Подтвердите план сбора' }).waitFor()
    await checkWidths('confirm')
    await ui.getByRole('button', { name: 'К предпросмотру', exact: true }).click()
    await ui.getByRole('heading', { name: 'Предпросмотр готов' }).waitFor()
    await ui.getByRole('button', { name: 'К подтверждению', exact: true }).click()
    await ui.getByRole('button', { name: 'Подтвердить план и запустить', exact: true }).click()
    await ui.getByRole('button', { name: 'Пауза', exact: true }).waitFor()
    const mutations = await page.evaluate(() =>
      window.__scoutTest.calls
        .filter(([method, url]) => method === 'post' && /\/(approve|start)\/$/.test(url))
        .map(([, url]) => url.split('/').at(-2)),
    )
    assert.deepEqual(mutations, ['approve', 'start'])
    await page.evaluate(() => {
      window.__scoutTest.networkDown = true
    })
    await ui.getByRole('alert').filter({ hasText: 'Не удалось обновить состояние' }).waitFor()
    assert.equal(await ui.getByRole('button', { name: 'Пауза', exact: true }).isDisabled(), true)
    await page.evaluate(() => {
      window.__scoutTest.networkDown = false
    })
    await ui.getByRole('button', { name: 'Повторить', exact: true }).click()
    await ui.getByRole('button', { name: 'Пауза', exact: true }).waitFor({ state: 'visible' })
    await ui
      .getByRole('alert')
      .filter({ hasText: 'Не удалось обновить состояние' })
      .waitFor({ state: 'hidden' })

    // A pause request is pending until the server confirms the paused state.
    await ui.getByRole('button', { name: 'Пауза', exact: true }).click()
    await ui.getByRole('heading', { name: 'Останавливаем выдачу новых задач' }).waitFor()
    assert.equal(await ui.getByRole('button', { name: 'Продолжить', exact: true }).count(), 0)
    await page.evaluate(() => window.__scoutTest.setStatus('paused'))
    await ui.getByRole('button', { name: 'Продолжить', exact: true }).waitFor()
    await ui.getByRole('button', { name: 'Продолжить', exact: true }).click()

    await page.evaluate(() => window.__scoutTest.setStatus('completed'))
    await ui.getByRole('heading', { name: 'Завершён', exact: true }).waitFor()
    await ui
      .getByRole('button', { name: 'Происхождение поля «title»: Событие 1', exact: true })
      .click()
    await ui.getByRole('heading', { name: 'Откуда взялось значение: title' }).waitFor()
    assert.match(await ui.locator('.scout-evidence').innerText(), /events\.example/)
    assert.equal(
      await ui.getByRole('button', { name: 'Происхождение поля «count»: 0', exact: true }).count(),
      10,
    )
    const routeBefore = await page.evaluate(() => location.hash)
    const pageTwo = ui.locator('.ergo-pagination').getByRole('button', { name: '2', exact: true })
    await pageTwo.click()
    await ui
      .getByRole('button', { name: 'Происхождение поля «title»: Событие 11', exact: true })
      .waitFor()
    const routeAfter = await page.evaluate(() => location.hash)
    for (const key of ['job=', 'run=']) {
      assert.match(routeBefore, new RegExp(key))
      assert.match(routeAfter, new RegExp(key))
    }

    for (const theme of ['Тёмная', 'Светлая']) {
      await ui.getByRole('button', { name: 'Тема оформления', exact: true }).click()
      await page.getByRole('link', { name: theme, exact: true }).click()
      assert.equal(
        await page.locator('html').getAttribute('data-bs-theme'),
        theme === 'Тёмная' ? 'dark' : 'light',
      )
      await checkWidths(theme === 'Тёмная' ? 'result-dark' : 'result-light')
    }
    for (const width of [1440, 768, 360, 320]) {
      await page.setViewportSize({ width, height: 1100 })
      const box = await ui.evaluate((element) => ({
        width: element.clientWidth,
        scroll: element.scrollWidth,
      }))
      assert.ok(
        box.scroll <= box.width + 2,
        `Horizontal overflow at ${width}: ${JSON.stringify(box)}`,
      )
    }
    await page.setViewportSize({ width: 1440, height: 1100 })
    await page.screenshot({ path: path.join(output, 'result-desktop.png'), fullPage: true })
    assert.deepEqual(errors, [])
    console.log(
      'Scout browser checks passed: mode availability, draft, system event, preview, approval/start, pending pause, all records, provenance, pagination, themes, 320–1440px.',
    )
  } catch (error) {
    if (page) {
      await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true })
      const state = await page.evaluate(() => ({
        calls: window.__scoutTest?.calls,
        hash: location.hash,
        text: document.body.innerText,
      }))
      fs.writeFileSync(path.join(output, 'failure.json'), JSON.stringify(state, null, 2))
    }
    throw error
  } finally {
    await browser.close()
  }
}
main().catch((error) => {
  console.error(error.message)
  process.exitCode = 1
})
