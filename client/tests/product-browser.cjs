const assert = require('node:assert/strict')
const path = require('node:path')
const { pathToFileURL } = require('node:url')
module.exports = async (browser, output) => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  try {
    await page.goto(pathToFileURL(path.join(output, 'fixture.html')).href + '#/product')
    const ui = page.locator('.scout-workflow')
    await ui.locator('.scout-mode').nth(2).click()
    await ui.getByRole('button', { name: 'Далее: источник и правила' }).click()
    await ui.getByLabel('URL примера').fill('https://books.toscrape.com/')
    await ui.getByRole('button', { name: 'Загрузить страницу', exact: true }).click()
    await ui.getByText('Снимок страницы ✓', { exact: true }).waitFor()
    await ui.locator('#scout-goal').fill('Название и цена книги')
    await page.evaluate(() => {
      window.__scoutTest.suggestionError = true
    })
    await ui.getByRole('button', { name: 'Предложить параметры', exact: true }).click()
    await ui.getByRole('alert').filter({ hasText: 'Модель временно недоступна' }).waitFor()
    assert.equal(await ui.locator('#scout-goal').inputValue(), 'Название и цена книги')
    await page.evaluate(() => {
      window.__scoutTest.suggestionError = false
    })
    await ui.getByRole('button', { name: 'Предложить параметры', exact: true }).click()
    await ui.getByRole('button', { name: 'Применить предложение', exact: true }).click()
    await ui.locator('#scout-selector-0').waitFor()
    assert.equal(await ui.locator('#scout-selector-0').inputValue(), 'h3')
    assert.equal(await ui.locator('#scout-selector-1').inputValue(), '.price_color')
    await ui.locator('.scout-crawl-editor > summary').click()
    await ui.locator('#scout-crawl-site').check()
    await ui.locator('.scout-plan-options > summary').click()
    const options = ui.locator('.scout-plan-options')
    await options.getByRole('button', { name: 'Обновить список' }).click()
    await options.getByLabel('Подключение', { exact: true }).selectOption('proxy-v1')
    await options.getByRole('button', { name: 'Проверить подключение' }).click()
    await options.getByText('Подключение проверено', { exact: true }).waitFor()
    await options.getByLabel('Адрес XML-карты').fill('https://books.toscrape.com/sitemap.xml')
    await options.getByLabel('Искать XML-карты в robots.txt').check()
    await options.getByRole('button', { name: 'Добавить тип', exact: true }).click()
    await options.getByLabel('Имя типа', { exact: true }).fill('catalog')
    await ui.getByRole('button', { name: 'Получить предпросмотр', exact: true }).click()
    await ui.getByText('Предпросмотр готов', { exact: true }).waitFor()
    const plan = await page.evaluate(() => window.__scoutTest.job.revision)
    assert.equal(plan.proxy_profile_revision_public_id, 'proxy-v1')
    assert.equal(plan.crawl.page_types[0].id, 'catalog')
    assert.equal(plan.crawl.sitemap_from_robots, true)
    assert.equal(plan.fields[1].conversion.type, 'money')
    assert.equal(
      await page.evaluate(() => window.__scoutTest.calls.some((c) => c[1]?.endsWith('/start/'))),
      false,
    )
    await page.goto(pathToFileURL(path.join(output, 'fixture.html')).href + '#/product')
    await page.reload()
    await ui.locator('.scout-mode').nth(2).click()
    await ui.getByRole('button', { name: 'Далее: источник и правила' }).click()
    await ui.getByRole('button', { name: 'Добавить тип страницы', exact: true }).click()
    for (let index = 0; index < 2; index++) {
      await ui
        .getByLabel('URL примера', { exact: true })
        .nth(index)
        .fill('https://books.toscrape.com/' + index)
      await ui.getByRole('button', { name: 'Загрузить страницу', exact: true }).nth(index).click()
    }
    await page.waitForFunction(
      () =>
        document.querySelectorAll('fieldset p[role=status]').length === 2 &&
        [...document.querySelectorAll('fieldset p[role=status]')].every((p) =>
          p.textContent.includes('✓'),
        ),
    )
    await ui.locator('#scout-goal').fill('Название и цена с двух типов страниц')
    await page.evaluate(() => {
      window.__scoutTest.deferSuggestion = true
    })
    await ui.getByRole('button', { name: 'Предложить параметры', exact: true }).click()
    await page.waitForFunction(() => !!window.__scoutTest.releaseSuggestion)
    const request = await page.evaluate(
      () => window.__scoutTest.calls.find((c) => c[1] === 'scout/plan-suggestions/')[2],
    )
    assert.equal(request.pages.length, 2)
    assert.equal('snapshot_public_id' in request, false)
    await ui.getByRole('button', { name: 'Изменить способ', exact: true }).click()
    await ui.locator('.scout-mode').first().click()
    await ui.getByRole('button', { name: 'Далее: источник и правила' }).click()
    await page.evaluate(() => window.__scoutTest.releaseSuggestion())
    assert.equal(await ui.locator('#scout-name-0').inputValue(), '') + assert.deepEqual(errors, [])
    console.log(
      'FE-001 passed: AI unavailable/retry/apply, manual draft, conversion, proxy selection/check, sitemap and page types reach common preview; no automatic start.',
    )
  } finally {
    await page.close()
  }
}
