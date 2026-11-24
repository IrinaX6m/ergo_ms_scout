const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

module.exports = async (browser, output) => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  try {
    await page.goto(pathToFileURL(path.join(output, 'fixture.html')).href + '#/product')
    const ui = page.locator('.scout-workflow')
    await ui.locator('.scout-mode').nth(1).click()
    await ui.getByRole('button', { name: 'Далее: источник и правила' }).click()
    await ui.locator('#scout-visual-url').fill('https://books.toscrape.com/')
    await ui.getByRole('button', { name: 'Загрузить страницу', exact: true }).click()

    const first = ui.locator('[role=treeitem][data-node=n1]')
    const image = ui.locator('[role=treeitem][data-node=n61]')
    const button = ui.getByRole('button', { name: 'Скачать изображение', exact: true })
    await first.press('ArrowRight')
    await image.waitFor()
    await first.press('ArrowRight')
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('ArrowDown')
    assert(await image.evaluate((node) => document.activeElement === node))
    await page.keyboard.press('Enter')
    await button.waitFor()
    const downloads = () =>
      page.evaluate(() => window.__scoutTest.calls.filter(([method]) => method === 'download'))
    assert.deepEqual(await downloads(), [])
    const frame = page.frameLocator('.scout-snapshot-frame iframe')
    assert.equal(await frame.locator('[data-scout-node=n61]').textContent(), '')
    assert.equal(await frame.locator('img,[src]').count(), 0)

    const [file] = await Promise.all([page.waitForEvent('download'), button.press('Enter')])
    assert.equal(file.suggestedFilename(), 'scout-n61.png')
    assert.match((await fs.readFile(await file.path())).toString('hex'), /^89504e470d0a1a0a/)
    assert.deepEqual(await downloads(), [
      [
        'download',
        'scout/visual-snapshots/visual-1/image/',
        {
          node_id: 'n61',
          tree_version: 'dom-v1:' + 'a'.repeat(64),
        },
      ],
    ])
    await page.evaluate(() => {
      window.__scoutTest.visual.imageHeaders = {
        'content-disposition': 'attachment; filename="cover.png"',
      }
    })
    const [named] = await Promise.all([page.waitForEvent('download'), button.click()])
    assert.equal(named.suggestedFilename(), 'cover.png')

    const unexpected = []
    page.on('download', (file) => unexpected.push(file.suggestedFilename()))
    await page.evaluate(() => {
      window.__scoutTest.visual.imageMime = 'text/html'
    })
    await button.click()
    await ui.getByText('Для скачивания поддерживаются JPEG, PNG, GIF и WebP.').waitFor()
    await page.evaluate(() => {
      window.__scoutTest.visual.imageError = 409
    })
    await button.click()
    await ui.getByText('Снимок изменился или истёк.', { exact: false }).waitFor()

    await page.evaluate(() => {
      Object.assign(window.__scoutTest.visual, { imageError: 0, imageMime: '', defer: 'image' })
    })
    await button.click()
    const busy = ui.getByRole('button', { name: 'Скачиваем изображение…' })
    assert(await busy.isDisabled())
    await first.click()
    await button.waitFor({ state: 'detached' })
    await page.evaluate(() => window.__scoutTest.visual.release())
    await image.press('Enter')
    await button.waitFor()
    await page.evaluate(() => {
      window.__scoutTest.visual.defer = 'image'
    })
    await button.click()
    await busy.waitFor()
    await ui.locator('.scout-visual-source button').click()
    await first.waitFor()
    await page.evaluate(() => window.__scoutTest.visual.release())
    await first.press('ArrowRight')
    await image.press('Enter')
    await button.waitFor()
    assert.deepEqual(unexpected, [])
    console.log(
      'Selected image download passed: keyboard, binary file, errors and stale responses.',
    )
  } finally {
    await page.close()
  }
}
