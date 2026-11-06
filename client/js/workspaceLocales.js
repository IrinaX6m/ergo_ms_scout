export default {
  ru: {
    job: 'Задание Scout',
    modeLabel: 'Способ работы',
    chooseMode: 'Как подготовим задание?',
    modeHint:
      'Выберите способ. Перед основным сбором вы проверите примеры и подтвердите общий план.',
    notAvailable: 'Пока недоступно',
    theme: 'Тема оформления',
    systemSettings: 'Настройки системы',
    themes: { light: 'Светлая', dark: 'Тёмная', auto: 'Системная' },
    stepsLabel: 'Этапы задания',
    steps: {
      mode: 'Способ работы',
      source: 'Источник и правила',
      preview: 'Предпросмотр',
      confirm: 'Подтверждение',
      collect: 'Выполнение',
      result: 'Результат',
    },
    leads: {
      mode: 'Три способа подготовить единый план сбора',
      source: 'Укажите источник, поля и правила извлечения',
      preview: 'Проверьте найденные значения до запуска',
      confirm: 'Проверьте и подтвердите конкретный план',
      collect: 'Следите за обработкой страниц',
      result: 'Проверьте записи и сохраните результат',
    },
    modes: {
      manual: {
        title: 'Вручную',
        description:
          'Задайте поля, CSS/XPath и правило карточки. Система проверит их на полученной странице.',
      },
      visual: {
        title: 'Кликами по странице',
        description:
          'Выберите элементы на сохранённой странице, чтобы получить правила извлечения.',
        unavailable:
          'Визуальный выбор ещё не подключён. Получить страницу для выбора элементов сейчас нельзя. Используйте ручные правила.',
      },
      ai: {
        title: 'Запрос к языковой модели',
        description:
          'Опишите цель. Модель предложит поля, правила и параметры по полученной странице.',
        unavailable:
          'Подготовка плана языковой моделью ещё не подключена. Запрос можно оставить в черновике и перейти к ручным правилам.',
      },
    },
    toSource: 'Далее: источник и правила',
    changeMode: 'Изменить способ',
    sourceHint:
      'Открытая HTML-страница. Доступность источника и допустимость адреса проверяет сервер.',
    rulesHint:
      'Укажите имя каждого поля и правило извлечения. Примеры станут доступны после проверки страницы.',
    recordUnit: 'Что считать одной записью',
    fieldOptions: 'Дополнительные правила поля',
    removeField: 'Убрать поле {number}',
    collectionBounds: 'Границы сбора',
    requestLimits: 'Лимиты загрузки',
    requestBudget: 'До {bytes} байт на ответ, таймаут {seconds} с.',
    crawlRule: { prefix: 'начинается с', contains: 'содержит' },
    previewPageLimit: 'Предпросмотр: до {pages} страниц.',
    previewAddresses: 'Адреса предпросмотра',
    ignoredQueryParams: 'Исключаемые параметры адреса: {params}.',
    boundsHint:
      'Эти ограничения входят в план задания. По умолчанию обрабатывается только указанная страница.',
    previewOnly: 'Основной сбор начинается только после подтверждения плана.',
    preparePreview: 'Получить предпросмотр',
    request: 'Какой результат нужен?',
    requestHint: 'Черновик сохраняется при переключении способов в пределах открытой страницы.',
    draftPreserved:
      'Адрес, введённые правила и черновик запроса сохраняются при переключении способов.',
    useManual: 'Перейти к ручным правилам',
    previewLead:
      'Это примеры по сохранённому снимку. Нажмите значение, чтобы проверить его происхождение.',
    toConfirmation: 'К подтверждению',
    toPreview: 'К предпросмотру',
    editRules: 'Изменить правила',
    confirmPlan: 'Подтвердите план сбора',
    beforeStart: 'Предпросмотр проверен. Основной сбор ещё не начат.',
    confirmHint:
      'После запуска значения извлекаются по этим правилам без языковой модели. Изменение плана требует нового предпросмотра и подтверждения.',
    confirmAndRun: 'Подтвердить план и запустить',
    planTitle: 'План задания',
    commonPath: 'Общий путь',
    planState: 'Состояние плана',
    planApproved: 'Подтверждён',
    planWaiting: 'Ожидает подтверждения',
    resultFields: 'Поля результата',
    notSpecified: 'Не указано',
    notReported: 'Сведения не получены',
    siteBounds: 'Сайт · глубина до {depth} · не более {pages} страниц',
    planChanged:
      'Предпросмотр не соответствует текущему плану или задание ещё загружается. Для изменённых правил получите новый предпросмотр.',
    fieldErrors: {
      required: 'Укажите имя поля и селектор.',
      duplicate: 'Имена полей должны быть разными.',
    },
    returning: 'Дождитесь подтверждения отмены. Затем вернёмся к правилам задания.',
    connectionLost:
      'Не удалось обновить состояние. Сбор может продолжаться. Показаны последние полученные сведения.',
    retry: 'Повторить',
    recordsFailed: 'Не удалось получить записи. Последние загруженные данные сохранены.',
    loadJobFailed: 'Не удалось загрузить задание. Обновите страницу или откройте его снова.',
    draftKept:
      'При получении ответа форма уже изменилась. Ваш черновик сохранён; проверьте его снова.',
    startFailed: 'Не удалось начать сбор. Проверьте состояние перед повторным запуском.',
    newJobConfirm:
      'Текущее задание занимает место сбора. Отменить его запуск и создать новое? Полученные записи сохранятся.',
    discardDraft: 'Начать новое задание? Введённые правила текущей формы будут сброшены.',
    cancelConfirm: 'Отменить текущий сбор? Уже полученные записи сохранятся.',
    processingOrder: 'Порядок обработки',
    noPercentage:
      'Загрузка и извлечение идут отдельно. Пока объём обхода неизвестен, итоговый процент не рассчитывается.',
    foundUrls: 'Найдено адресов: {count}',
    partialResult:
      'Получен частичный результат. Проверьте ошибки и ограничения обхода перед использованием записей.',
    metrics: {
      fetched: 'Загружено страниц',
      extracted: 'Разобрано страниц',
      records: 'Получено записей',
      errors: 'Ошибок',
    },
    execution: {
      running: 'Обработка идёт по подтверждённому плану.',
      pausing: 'Сервер завершает текущие операции перед паузой.',
      paused: 'Новые задачи не выдаются. Можно продолжить или отменить сбор.',
      cancelling: 'Ожидаем подтверждения отмены от сервера.',
    },
    pipeline: {
      fetch: { title: 'Загрузчик', description: 'Получает страницы и сохраняет HTML-снимки.' },
      crawl: {
        title: 'Обработчик ссылок',
        description: 'Находит адреса в пределах подтверждённых границ.',
      },
      extract: {
        title: 'Обработчик извлечения',
        description: 'Применяет правила к сохранённым страницам.',
      },
      records: {
        title: 'Записи и происхождение',
        description: 'Сохраняет значения и источники полей.',
      },
    },
    valueOrigin: 'Происхождение поля «{field}»: {value}',
    rawValue: 'Исходное значение',
    noEvidence: 'Сервер не передал происхождение этого поля.',
    closeEvidence: 'Закрыть происхождение значения',
  },
  en: {
    job: 'Scout job',
    modeLabel: 'Working mode',
    chooseMode: 'How shall we prepare the job?',
    modeHint:
      'Choose a mode. You will review examples and confirm the shared plan before collection.',
    notAvailable: 'Not yet available',
    theme: 'Appearance',
    systemSettings: 'System settings',
    themes: { light: 'Light', dark: 'Dark', auto: 'System' },
    stepsLabel: 'Job steps',
    steps: {
      mode: 'Working mode',
      source: 'Source and rules',
      preview: 'Preview',
      confirm: 'Confirmation',
      collect: 'Execution',
      result: 'Result',
    },
    leads: {
      mode: 'Three ways to prepare one collection plan',
      source: 'Define the source, fields and extraction rules',
      preview: 'Review the extracted values before starting',
      confirm: 'Review and confirm this specific plan',
      collect: 'Follow page processing',
      result: 'Review records and download the result',
    },
    modes: {
      manual: {
        title: 'Manual rules',
        description:
          'Enter fields, CSS/XPath and the record selector. The system checks them against the fetched page.',
      },
      visual: {
        title: 'Select page elements',
        description: 'Select elements on a saved page to create extraction rules.',
        unavailable:
          'Visual selection is not connected yet. The saved page cannot currently be opened for element selection. Use manual rules.',
      },
      ai: {
        title: 'Language model request',
        description:
          'Describe your goal. The model proposes fields, rules and parameters from the fetched page.',
        unavailable:
          'Language model planning is not connected yet. Keep your request as a draft and switch to manual rules.',
      },
    },
    toSource: 'Next: source and rules',
    changeMode: 'Change mode',
    sourceHint: 'An open HTML page. The server checks availability and allowed addresses.',
    rulesHint:
      'Enter each field name and extraction rule. Examples become available after checking the page.',
    recordUnit: 'What counts as one record',
    fieldOptions: 'Additional field rules',
    removeField: 'Remove field {number}',
    collectionBounds: 'Collection boundaries',
    requestLimits: 'Download limits',
    requestBudget: 'Up to {bytes} bytes per response, timeout {seconds} s.',
    crawlRule: { prefix: 'starts with', contains: 'contains' },
    previewPageLimit: 'Preview: up to {pages} pages.',
    previewAddresses: 'Preview URLs',
    ignoredQueryParams: 'Excluded URL parameters: {params}.',
    boundsHint:
      'These limits belong to the job plan. By default, only the specified page is processed.',
    previewOnly: 'Collection starts only after the plan is confirmed.',
    preparePreview: 'Prepare preview',
    request: 'What result do you need?',
    requestHint: 'Your draft is retained when switching modes on the current page.',
    draftPreserved: 'The address, rules and request draft are retained when you switch modes.',
    useManual: 'Use manual rules',
    previewLead:
      'These are examples from the saved snapshot. Select a value to inspect its origin.',
    toConfirmation: 'Review confirmation',
    toPreview: 'Back to preview',
    editRules: 'Edit rules',
    confirmPlan: 'Confirm the collection plan',
    beforeStart: 'The preview has been reviewed. Collection has not started yet.',
    confirmHint:
      'Values will be extracted using these rules without a language model. Changed plans require a new preview and confirmation.',
    confirmAndRun: 'Confirm plan and start',
    planTitle: 'Job plan',
    commonPath: 'Shared workflow',
    planState: 'Plan status',
    planApproved: 'Confirmed',
    planWaiting: 'Awaiting confirmation',
    resultFields: 'Result fields',
    notSpecified: 'Not specified',
    notReported: 'Not reported',
    siteBounds: 'Site · depth up to {depth} · at most {pages} pages',
    planChanged:
      'The preview does not match the current plan, or the job is still loading. Prepare a new preview for changed rules.',
    fieldErrors: {
      required: 'Enter a field name and selector.',
      duplicate: 'Field names must be unique.',
    },
    returning: 'Wait for cancellation to be confirmed before returning to the job rules.',
    connectionLost:
      'The state could not be refreshed. Collection may still be running. The last known state is shown.',
    retry: 'Retry',
    recordsFailed: 'Records could not be loaded. Previously loaded data has been retained.',
    loadJobFailed: 'The job could not be loaded. Refresh the page or open it again.',
    draftKept:
      'The form changed while waiting for a response. Your draft is retained; check it again.',
    startFailed: 'Collection could not start. Check its state before retrying.',
    newJobConfirm:
      'The current job occupies the collection slot. Cancel its run and create a new job? Collected records will be retained.',
    discardDraft: 'Start a new job? The current form rules will be reset.',
    cancelConfirm: 'Cancel this collection? Already collected records will be retained.',
    processingOrder: 'Processing order',
    noPercentage:
      'Fetching and extraction are separate. No final percentage is shown while the crawl size is unknown.',
    foundUrls: 'Discovered URLs: {count}',
    partialResult:
      'The result is partial. Review errors and crawl boundaries before using the records.',
    metrics: {
      fetched: 'Pages fetched',
      extracted: 'Pages extracted',
      records: 'Records collected',
      errors: 'Errors',
    },
    execution: {
      running: 'Processing follows the confirmed plan.',
      pausing: 'The server is finishing current operations before pausing.',
      paused: 'No new tasks are dispatched. Resume or cancel collection.',
      cancelling: 'Waiting for the server to confirm cancellation.',
    },
    pipeline: {
      fetch: { title: 'Fetcher', description: 'Fetches pages and saves HTML snapshots.' },
      crawl: {
        title: 'Link processor',
        description: 'Finds addresses within the confirmed boundaries.',
      },
      extract: { title: 'Extractor', description: 'Applies rules to saved pages.' },
      records: {
        title: 'Records and provenance',
        description: 'Saves values and their field sources.',
      },
    },
    valueOrigin: 'Origin of field “{field}”: {value}',
    rawValue: 'Original value',
    noEvidence: 'The server did not provide provenance for this field.',
    closeEvidence: 'Close value provenance',
  },
  fr: {
    job: 'Tâche Scout',
    modeLabel: 'Mode de travail',
    chooseMode: 'Comment préparer la tâche ?',
    modeHint:
      'Choisissez un mode. Vous vérifierez les exemples et confirmerez le plan commun avant la collecte.',
    notAvailable: 'Pas encore disponible',
    theme: 'Apparence',
    systemSettings: 'Paramètres du système',
    themes: { light: 'Clair', dark: 'Sombre', auto: 'Système' },
    stepsLabel: 'Étapes de la tâche',
    steps: {
      mode: 'Mode de travail',
      source: 'Source et règles',
      preview: 'Aperçu',
      confirm: 'Confirmation',
      collect: 'Exécution',
      result: 'Résultat',
    },
    leads: {
      mode: 'Trois façons de préparer un plan commun',
      source: 'Définissez la source, les champs et les règles',
      preview: 'Vérifiez les valeurs avant le démarrage',
      confirm: 'Vérifiez et confirmez ce plan précis',
      collect: 'Suivez le traitement des pages',
      result: 'Vérifiez les enregistrements et téléchargez le résultat',
    },
    modes: {
      manual: {
        title: 'Règles manuelles',
        description:
          'Saisissez les champs, CSS/XPath et le sélecteur de fiche. Le système les vérifie sur la page obtenue.',
      },
      visual: {
        title: 'Sélection sur la page',
        description: 'Sélectionnez les éléments d’une page enregistrée pour créer les règles.',
        unavailable:
          'La sélection visuelle n’est pas encore connectée. La page enregistrée ne peut pas être ouverte pour sélectionner des éléments. Utilisez les règles manuelles.',
      },
      ai: {
        title: 'Requête au modèle de langage',
        description:
          'Décrivez le résultat. Le modèle propose les champs, règles et paramètres à partir de la page.',
        unavailable:
          'La préparation du plan par modèle de langage n’est pas encore connectée. Gardez votre requête et passez aux règles manuelles.',
      },
    },
    toSource: 'Suite : source et règles',
    changeMode: 'Changer de mode',
    sourceHint:
      'Une page HTML ouverte. Le serveur vérifie sa disponibilité et les adresses autorisées.',
    rulesHint:
      'Indiquez le nom et la règle de chaque champ. Les exemples apparaissent après la vérification de la page.',
    recordUnit: 'Définition d’un enregistrement',
    fieldOptions: 'Règles supplémentaires du champ',
    removeField: 'Retirer le champ {number}',
    collectionBounds: 'Limites de collecte',
    requestLimits: 'Limites de téléchargement',
    requestBudget: 'Jusqu’à {bytes} octets par réponse, délai de {seconds} s.',
    crawlRule: { prefix: 'commence par', contains: 'contient' },
    previewPageLimit: 'Aperçu : jusqu’à {pages} pages.',
    previewAddresses: 'Adresses d’aperçu',
    ignoredQueryParams: 'Paramètres d’URL exclus : {params}.',
    boundsHint: 'Ces limites font partie du plan. Par défaut, seule la page indiquée est traitée.',
    previewOnly: 'La collecte commence uniquement après confirmation du plan.',
    preparePreview: 'Préparer l’aperçu',
    request: 'Quel résultat souhaitez-vous ?',
    requestHint: 'Le brouillon est conservé lors du changement de mode sur cette page.',
    draftPreserved:
      'L’adresse, les règles et la requête sont conservées lors du changement de mode.',
    useManual: 'Utiliser les règles manuelles',
    previewLead:
      'Exemples issus de la page enregistrée. Sélectionnez une valeur pour vérifier son origine.',
    toConfirmation: 'Vers la confirmation',
    toPreview: 'Retour à l’aperçu',
    editRules: 'Modifier les règles',
    confirmPlan: 'Confirmez le plan de collecte',
    beforeStart: 'L’aperçu a été vérifié. La collecte n’a pas encore commencé.',
    confirmHint:
      'Les valeurs seront extraites avec ces règles, sans modèle de langage. Un plan modifié exige un nouvel aperçu et une nouvelle confirmation.',
    confirmAndRun: 'Confirmer le plan et démarrer',
    planTitle: 'Plan de la tâche',
    commonPath: 'Parcours commun',
    planState: 'État du plan',
    planApproved: 'Confirmé',
    planWaiting: 'En attente de confirmation',
    resultFields: 'Champs du résultat',
    notSpecified: 'Non indiqué',
    notReported: 'Non communiqué',
    siteBounds: 'Site · profondeur {depth} · au plus {pages} pages',
    planChanged:
      'L’aperçu ne correspond pas au plan, ou la tâche est en cours de chargement. Préparez un nouvel aperçu des règles modifiées.',
    fieldErrors: {
      required: 'Indiquez un nom et un sélecteur.',
      duplicate: 'Les noms des champs doivent être uniques.',
    },
    returning: 'Attendez la confirmation de l’annulation avant de revenir aux règles.',
    connectionLost:
      'Impossible d’actualiser l’état. La collecte peut continuer. Le dernier état connu est affiché.',
    retry: 'Réessayer',
    recordsFailed:
      'Impossible de charger les enregistrements. Les données déjà chargées sont conservées.',
    loadJobFailed: 'Impossible de charger la tâche. Actualisez la page ou ouvrez-la à nouveau.',
    draftKept:
      'Le formulaire a changé pendant la requête. Le brouillon est conservé ; vérifiez-le à nouveau.',
    startFailed: 'Impossible de lancer la collecte. Vérifiez son état avant de réessayer.',
    newJobConfirm:
      'La tâche actuelle occupe la place de collecte. Annuler son exécution et créer une tâche ? Les enregistrements seront conservés.',
    discardDraft: 'Créer une tâche ? Les règles du formulaire actuel seront réinitialisées.',
    cancelConfirm: 'Annuler cette collecte ? Les enregistrements déjà obtenus seront conservés.',
    processingOrder: 'Ordre de traitement',
    noPercentage:
      'Le chargement et l’extraction sont séparés. Aucun pourcentage final n’est affiché si le volume est inconnu.',
    foundUrls: 'Adresses trouvées : {count}',
    partialResult:
      'Le résultat est partiel. Vérifiez les erreurs et les limites avant de l’utiliser.',
    metrics: {
      fetched: 'Pages chargées',
      extracted: 'Pages extraites',
      records: 'Enregistrements',
      errors: 'Erreurs',
    },
    execution: {
      running: 'Le traitement suit le plan confirmé.',
      pausing: 'Le serveur termine les opérations en cours avant la pause.',
      paused: 'Aucune nouvelle tâche n’est distribuée. Reprenez ou annulez la collecte.',
      cancelling: 'En attente de confirmation de l’annulation.',
    },
    pipeline: {
      fetch: {
        title: 'Chargement',
        description: 'Charge les pages et conserve les instantanés HTML.',
      },
      crawl: {
        title: 'Traitement des liens',
        description: 'Trouve les adresses dans les limites confirmées.',
      },
      extract: { title: 'Extraction', description: 'Applique les règles aux pages enregistrées.' },
      records: {
        title: 'Enregistrements et origine',
        description: 'Conserve les valeurs et leurs sources.',
      },
    },
    valueOrigin: 'Origine du champ « {field} » : {value}',
    rawValue: 'Valeur originale',
    noEvidence: 'Le serveur n’a pas fourni l’origine de ce champ.',
    closeEvidence: 'Fermer l’origine de la valeur',
  },
}
