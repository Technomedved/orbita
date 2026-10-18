"""Original Db2 exercises on fictional archive data. No database connections."""
COURSE_ID = 'db2'
CONTENT_VERSION = '1.0'
TOPICS = {'joins':'JOIN и сохранение строк','aggregation':'Подсчёты и кратность',
          'nulls':'NULL и отсутствие записей','windows':'Последняя версия и окна',
          'cte':'CTE и составные проверки','dates':'Диапазоны дат'}
SOURCES = {
    'platform':('IBM · SQL across Db2 platforms','https://community.ibm.com/community/user/blogs/lynn-chou/2018/10/01/the-sql-reference-for-cross-platform-development'),
    'join':('IBM Db2 LUW 11.1 · joined-table','https://www.ibm.com/docs/en/db2/11.1.0?topic=clause-joined-table'),
    'count':('IBM Db2 LUW 11.5 · COUNT','https://www.ibm.com/docs/en/db2/11.5.x?topic=functions-count'),
    'cte':('IBM Db2 LUW 11.5 · common-table-expression','https://www.ibm.com/docs/en/db2/11.5.x?topic=statement-common-table-expression'),
    'null':('IBM Db2 LUW 11.1 · IN predicate','https://www.ibm.com/docs/en/db2/11.1.0?topic=predicates-in-predicate'),
    'exists':('IBM Db2 for z/OS 12 · EXISTS','https://www.ibm.com/docs/en/db2-for-zos/12.0.0?topic=predicates-exists-predicate'),
    'olap':('IBM Db2 for i 7.6 · OLAP specifications','https://www.ibm.com/docs/en/i/7.6.0?topic=statement-using-olap-specifications'),
    'index':('IBM Db2 LUW 11.5 · index scans','https://www.ibm.com/docs/en/db2/11.5.x?topic=methods-data-access-through-index-scans'),
    'sqlref':('IBM Db2 LUW 12.1.2 · SQL Reference (PDF)','https://public.dhe.ibm.com/ps/products/db2/info/vr121/pdf/en_US/db2_sql_reference_1212.pdf'),
}
COMPATIBILITY = (
    'Платформа и версия твоей Db2 пока не указаны. DBeaver — клиент, а диалект задаёт сервер. '
    'Материалы используют обычные SELECT, JOIN, CASE, CTE и ROW_NUMBER; ссылки IBM помечены платформой. '
    'Это не гарантия совместимости с любой старой Db2. Проверь поддержку синтаксиса в руководстве своей версии. '
    'DDL, текущая схема, права и способы EXPLAIN отличаются между LUW, z/OS и IBM i. '
    'Настройка табличных пространств и платформенные команды в задания не включены. '
    'Запросы здесь не выполнялись на настоящей Db2. SQLite используется только для хранения учебного прогресса.'
)
SETUP_GUIDE = (
    'Для ручной практики выбери в DBeaver отдельное учебное соединение и схему. '
    'Скопируй учебный SQL-скрипт из вкладки «Данные». Он создаёт четыре таблицы ORB_* и добавляет 25 строк. '
    'Скрипт не содержит DROP и не рассчитан на повторный запуск в той же схеме. '
    'Приложение не подключается к серверу, не запускает SQL и не читает рабочие данные. '
    'Если учебной Db2 нет, разбирай набор данных и сравнивай рассуждение с ожидаемыми строками; '
    'результат фактического выполнения можно записать в заметки позже.'
)

TABLES = {
    'ORB_EMPLOYEES': {
        'columns':[('EMPLOYEE_ID','INTEGER NOT NULL PRIMARY KEY'),('FULL_NAME','VARCHAR(40) NOT NULL'),
                   ('DEPARTMENT','VARCHAR(12) NOT NULL'),('ACTIVE','CHAR(1) NOT NULL')],
        'rows':[(1,'Anna','IT','Y'),(2,'Boris','HR','Y'),(3,'Vera','HR','N'),(4,'Gleb','IT','Y')],
        'constraints':[]},
    'ORB_DOCS': {
        'columns':[('DOC_ID','INTEGER NOT NULL PRIMARY KEY'),('TITLE','VARCHAR(80) NOT NULL'),
                   ('OWNER_ID','INTEGER'),('ARCHIVE_CODE','VARCHAR(12) NOT NULL'),('CREATED_ON','DATE NOT NULL')],
        'rows':[(101,'Contract',1,'EHD','2026-10-01'),(102,'Application',2,'HR','2026-10-02'),
                (103,'Memo',None,'EHD','2026-10-03'),(104,'Order',3,'HR','2026-10-04'),
                (105,'Draft',1,'EHD','2026-10-05'),(106,'Policy',4,'HR','2026-10-05')],
        'constraints':['FOREIGN KEY (OWNER_ID) REFERENCES ORB_EMPLOYEES (EMPLOYEE_ID)']},
    'ORB_VERSIONS': {
        'columns':[('VERSION_ID','INTEGER NOT NULL PRIMARY KEY'),('DOC_ID','INTEGER NOT NULL'),
                   ('VERSION_NO','INTEGER NOT NULL'),('CREATED_AT','TIMESTAMP NOT NULL'),
                   ('STATE','VARCHAR(12) NOT NULL'),('BYTE_SIZE','INTEGER NOT NULL')],
        'rows':[(1001,101,1,'2026-10-01 09:00:00','DRAFT',100),
                (1002,101,2,'2026-10-03 00:00:00','PUBLISHED',120),
                (1003,102,1,'2026-10-02 08:00:00','PUBLISHED',200),
                (1004,102,2,'2026-10-04 12:00:00','ARCHIVED',210),
                (1005,103,1,'2026-10-03 14:00:00','DRAFT',80),
                (1006,104,1,'2026-10-04 15:00:00','PUBLISHED',300),
                (1007,104,2,'2026-10-04 15:00:00','PUBLISHED',320),
                (1008,106,1,'2026-10-05 00:00:00','PUBLISHED',150)],
        'constraints':['FOREIGN KEY (DOC_ID) REFERENCES ORB_DOCS (DOC_ID)','UNIQUE (DOC_ID, VERSION_NO)']},
    'ORB_GRANTS': {
        'columns':[('GRANT_ID','INTEGER NOT NULL PRIMARY KEY'),('DOC_ID','INTEGER NOT NULL'),
                   ('EMPLOYEE_ID','INTEGER'),('ACCESS_CODE','VARCHAR(8) NOT NULL')],
        'rows':[(1,101,1,'READ'),(2,101,2,'READ'),(3,101,1,'WRITE'),(4,102,2,'READ'),
                (5,104,2,'READ'),(6,106,4,'READ'),(7,103,None,'READ')],
        'constraints':['FOREIGN KEY (DOC_ID) REFERENCES ORB_DOCS (DOC_ID)',
                       'FOREIGN KEY (EMPLOYEE_ID) REFERENCES ORB_EMPLOYEES (EMPLOYEE_ID)']},
}


def fixture_sql():
    parts=['-- Orbita Db2 practice: fictional data, version '+CONTENT_VERSION,
           '-- Run manually in a dedicated learning schema. No DROP; not rerunnable unchanged.',
           '-- Check Db2 platform/version, schema permissions and DBeaver connection first.','']
    for name,table in TABLES.items():
        defs=[f'    {column} {dtype}' for column,dtype in table['columns']]
        defs += ['    '+constraint for constraint in table['constraints']]
        parts.append('CREATE TABLE '+name+' (\n'+',\n'.join(defs)+'\n);')
        for row in table['rows']:
            values=[]
            for value,(_,dtype) in zip(row,table['columns']):
                if value is None:literal='NULL'
                elif isinstance(value,int):literal=str(value)
                else:
                    literal="'"+value.replace("'","''")+"'"
                    if dtype.startswith('TIMESTAMP'):literal='TIMESTAMP('+literal+')'
                    elif dtype.startswith('DATE'):literal='DATE('+literal+')'
                values.append(literal)
            parts.append('INSERT INTO '+name+' ('+', '.join(c[0] for c in table['columns'])+') VALUES ('+', '.join(values)+');')
        parts.append('')
    return '\n'.join(parts)


LATEST_SQL = '''WITH ranked AS (
    SELECT v.*, ROW_NUMBER() OVER (
        PARTITION BY v.DOC_ID
        ORDER BY v.CREATED_AT DESC, v.VERSION_NO DESC, v.VERSION_ID DESC
    ) AS RN
    FROM ORB_VERSIONS v
)
SELECT d.DOC_ID, r.VERSION_ID, r.VERSION_NO, r.STATE
FROM ORB_DOCS d
LEFT JOIN ranked r ON r.DOC_ID = d.DOC_ID AND r.RN = 1
ORDER BY d.DOC_ID;'''

ABSENT_SQL = '''SELECT d.DOC_ID, d.TITLE
FROM ORB_DOCS d
WHERE NOT EXISTS (
    SELECT 1 FROM ORB_GRANTS g
    JOIN ORB_EMPLOYEES e ON e.EMPLOYEE_ID = g.EMPLOYEE_ID AND e.ACTIVE = 'Y'
    WHERE g.DOC_ID = d.DOC_ID AND g.ACCESS_CODE = 'READ'
)
ORDER BY d.DOC_ID;'''

DATES_SQL = '''SELECT VERSION_ID, DOC_ID, CREATED_AT
FROM ORB_VERSIONS
WHERE STATE = 'PUBLISHED'
  AND CREATED_AT >= TIMESTAMP('2026-10-03 00:00:00')
  AND CREATED_AT <  TIMESTAMP('2026-10-05 00:00:00')
ORDER BY DOC_ID, VERSION_ID;'''

LESSONS = [
dict(id='diagnostic',title='Диагностика: четыре ситуации из архива',minutes='10–15',
     topics=list(TOPICS),prerequisites=[],goal='Отметить пробелы по своему решению и самопроверке, без автоматической оценки SQL.',
     explanation='Не начинай с учебника целиком. На маленьком архиве проверь, где результат запроса может оказаться неожиданным. '
                 'Сначала запиши ответы и рассуждение, затем сравни с ожидаемым результатом в «Самопроверке» и оцени темы во вкладке «Самооценка».',
     task='A. Для документа 101 напрямую соедини ORB_DOCS с ORB_VERSIONS и ORB_GRANTS по DOC_ID. '
          'Сколько строк получится и почему это не количество документов?\n\n'
          'B. Найди документы без READ-права у активного сотрудника. Учти запись права с EMPLOYEE_ID = NULL.\n\n'
          'C. Выбери последнюю версию документа 104: сначала по CREATED_AT, затем по VERSION_NO и VERSION_ID. '
          'Почему одного MAX(CREATED_AT) недостаточно?\n\n'
          'D. Найди опубликованные версии за 3 и 4 октября 2026 года целиком. Укажи границы интервала и VERSION_ID.',
     expected={'columns':['Пункт','Ожидаемый результат'],
               'rows':[['A','6 строк: 2 версии × 3 записи прав'],['B','DOC_ID 103 и 105'],
                       ['C','VERSION_ID 1007, VERSION_NO 2'],['D','VERSION_ID 1002, 1006, 1007']]},
     hints=['Посмотри отдельно на число версий и записей прав у 101.',
            'Проверка B — отсутствие хотя бы одной подходящей записи, а не отсутствие строки в ORB_GRANTS вообще.',
            'Для C нужен порядок, разрешающий совпадения времени; для D — верхняя граница следующего дня.'],
     solution="""-- A
SELECT COUNT(*) AS JOINED_ROWS
FROM ORB_DOCS d
JOIN ORB_VERSIONS v ON v.DOC_ID = d.DOC_ID
JOIN ORB_GRANTS g ON g.DOC_ID = d.DOC_ID
WHERE d.DOC_ID = 101;

-- B
"""+ABSENT_SQL+'\n\n-- C: строка DOC_ID = 104 в результате\n'+LATEST_SQL+'\n\n-- D\n'+DATES_SQL,
     solution_notes='A: каждый вариант версии сочетается с каждой записью прав. B: NULL-получатель не является активным сотрудником. '
                    'C: у 1006 и 1007 одинаковое время; номер версии выбирает 1007. D: полуоткрытый интервал включает все времена 4 октября. '
                    'Отметки тем ниже — твоя самооценка, не результат исполнения SQL.',
     checks=['Объяснил кратность соединения, не только назвал число.',
             'Учёл NULL и признак ACTIVE.', 'Обосновал разрешение равных времён.',
             'После сравнения отметил темы, которые нужно повторить.'],sources=['platform','join','null','olap','sqlref']),
dict(id='joins',title='1. LEFT JOIN: сохранить документы без публикаций',minutes='15–20',
     topics=['joins'],prerequisites=[],goal='Получить полный список документов, включая документы с нулём опубликованных версий.',
     explanation='Отчёт архива должен содержать и документ без версий. Условие отбора правой таблицы определяет, '
                 'какие версии присоединятся. Проверка той же колонки в WHERE может убрать строки, созданные внешним соединением. '
                 'Сначала зафиксируй требование: одна итоговая строка на DOC_ID.',
     task='Для каждого документа выведи DOC_ID и PUBLISHED_COUNT — количество версий со STATE = PUBLISHED. '
          'Сохрани все шесть документов, отсортируй по DOC_ID. Не используй DISTINCT, чтобы скрыть ошибку соединения. '
          'В заметках объясни, чем изменится результат при переносе фильтра STATE из ON в WHERE.',
     expected={'columns':['DOC_ID','PUBLISHED_COUNT'],'rows':[[101,1],[102,1],[103,0],[104,2],[105,0],[106,1]]},
     hints=['Начни с ORB_DOCS и LEFT JOIN на ORB_VERSIONS.',
            "Условие v.STATE = 'PUBLISHED' помести в ON, рядом с DOC_ID.",
            'Сгруппируй по d.DOC_ID и считай ненулевой идентификатор версии, а не COUNT(*).'],
     solution="""SELECT d.DOC_ID, COUNT(v.VERSION_ID) AS PUBLISHED_COUNT
FROM ORB_DOCS d
LEFT JOIN ORB_VERSIONS v
    ON v.DOC_ID = d.DOC_ID AND v.STATE = 'PUBLISHED'
GROUP BY d.DOC_ID
ORDER BY d.DOC_ID;""",
     solution_notes='Для 103 нет опубликованных версий, для 105 нет версий вообще. COUNT(v.VERSION_ID) даёт ноль в обоих случаях. '
                    'COUNT(*) посчитал бы внешнюю строку как одну. Фильтр STATE в WHERE исключил бы оба документа из этого запроса.',
     checks=['В результате шесть строк.', 'У 103 и 105 ноль, у 104 две публикации.',
             'Могу объяснить влияние ON и WHERE на данном наборе.'],sources=['join','count']),
dict(id='aggregation',title='2. Два дочерних набора: отчёт без размножения',minutes='15–20',
     topics=['aggregation'],prerequisites=['joins'],goal='Раздельно посчитать версии и права, не перемножая дочерние строки.',
     explanation='У документа 101 две версии и три записи прав. Прямое соединение обоих дочерних наборов даёт шесть строк. '
                 'Нужные показатели имеют разный смысл: число версий, число записей прав, число различных ненулевых получателей. '
                 'Подготовь каждый показатель на уровне DOC_ID, затем соедини готовые итоги.',
     task='Выведи для всех документов DOC_ID, VERSION_COUNT, GRANT_COUNT, PRINCIPAL_COUNT. '
          'Последний показатель — число различных EMPLOYEE_ID, исключая NULL. Учитывай любые ACCESS_CODE. '
          'Документы без дочерних строк должны иметь нули. Используй два CTE или эквивалентные производные таблицы.',
     expected={'columns':['DOC_ID','VERSION_COUNT','GRANT_COUNT','PRINCIPAL_COUNT'],
               'rows':[[101,2,3,2],[102,2,1,1],[103,1,1,0],[104,2,1,1],[105,0,0,0],[106,1,1,1]]},
     hints=['Сначала отдельно GROUP BY DOC_ID в ORB_VERSIONS и ORB_GRANTS.',
            'Для прав нужны COUNT(*) и COUNT(DISTINCT EMPLOYEE_ID): это разные показатели.',
            'Соедини итоги с ORB_DOCS через LEFT JOIN; пропуски показателей замени COALESCE(..., 0).'],
     solution='''WITH version_counts AS (
    SELECT DOC_ID, COUNT(*) AS VERSION_COUNT FROM ORB_VERSIONS GROUP BY DOC_ID
), grant_counts AS (
    SELECT DOC_ID, COUNT(*) AS GRANT_COUNT,
           COUNT(DISTINCT EMPLOYEE_ID) AS PRINCIPAL_COUNT
    FROM ORB_GRANTS GROUP BY DOC_ID
)
SELECT d.DOC_ID, COALESCE(v.VERSION_COUNT, 0) AS VERSION_COUNT,
       COALESCE(g.GRANT_COUNT, 0) AS GRANT_COUNT,
       COALESCE(g.PRINCIPAL_COUNT, 0) AS PRINCIPAL_COUNT
FROM ORB_DOCS d
LEFT JOIN version_counts v ON v.DOC_ID = d.DOC_ID
LEFT JOIN grant_counts g ON g.DOC_ID = d.DOC_ID
ORDER BY d.DOC_ID;''',
     solution_notes='В каждом CTE максимум одна строка на документ, поэтому итоговые соединения не умножают показатели. '
                    'У 103 запись права существует, но получатель NULL: GRANT_COUNT = 1, PRINCIPAL_COUNT = 0. '
                    'Один DISTINCT поверх готового неправильного отчёта не исправляет уже посчитанные суммы.',
     checks=['У 101 показатели 2 / 3 / 2, а не 6.', 'У 103 различаю запись права и получателя.',
             'Объяснил, почему предагрегация сохраняет уровень детализации.'],sources=['count','cte']),
dict(id='nulls',title='3. Нет действующего права: NOT EXISTS и NULL',minutes='15–20',
     topics=['nulls'],prerequisites=['joins'],goal='Найти отсутствие действующего доступа, учитывая неполные назначения прав.',
     explanation='Наличие строки в таблице прав ещё не означает, что читать может активный сотрудник. '
                 'Действующим здесь считаем только READ у сотрудника с ACTIVE = Y. '
                 'Строка с NULL-получателем условию не отвечает. Опиши существование подходящей строки и затем отрицай его.',
     task='Найди DOC_ID и TITLE документов, у которых нет ни одного READ-права для активного сотрудника. '
          'Используй коррелированный NOT EXISTS. Дополнительно объясни, почему запрос сотрудников '
          'с EMPLOYEE_ID NOT IN (SELECT EMPLOYEE_ID FROM ORB_GRANTS) опасен на этих данных.',
     expected={'columns':['DOC_ID','TITLE'],'rows':[[103,'Memo'],[105,'Draft']]},
     hints=['В подзапросе соедини право с сотрудником.',
            "Отбери ACCESS_CODE = 'READ' и ACTIVE = 'Y', свяжи g.DOC_ID с внешним d.DOC_ID.",
            'Оберни подзапрос в NOT EXISTS. Для дополнительного вопроса найди NULL в ORB_GRANTS.'],
     solution=ABSENT_SQL,
     solution_notes='У 103 есть READ с NULL-получателем, у 105 нет прав. Для остальных есть активный читатель. '
                    'Подзапрос NOT IN с NULL может сделать проверку неизвестной даже для отсутствующего значения; '
                    'WHERE не оставляет неизвестные условия. Не путай NULL с нулём или пустой строкой.',
     checks=['Вернул именно 103 и 105.', 'Не исключил 104: активный читатель Boris у него есть.',
             'Объяснил влияние NULL на дополнительный NOT IN.'],sources=['null','exists']),
dict(id='windows',title='4. Последняя версия: порядок при одинаковом времени',minutes='15–20',
     topics=['windows'],prerequisites=[],goal='Выбирать ровно одну последнюю версию детерминированно.',
     explanation='У документа 104 две версии имеют одинаковый CREATED_AT. Соединение с MAX(CREATED_AT) вернёт обе. '
                 'Определение «последняя» должно включать правила разрешения совпадений. '
                 'Здесь порядок: CREATED_AT DESC, VERSION_NO DESC, VERSION_ID DESC.',
     task='Для каждого документа выведи DOC_ID, VERSION_ID, VERSION_NO, STATE последней версии любого статуса. '
          'Документ без версий сохрани с NULL. Используй ROW_NUMBER в отдельном CTE или подзапросе. '
          'Объясни, почему фильтровать только PUBLISHED до нумерации означало бы другую задачу.',
     expected={'columns':['DOC_ID','VERSION_ID','VERSION_NO','STATE'],
               'rows':[[101,1002,2,'PUBLISHED'],[102,1004,2,'ARCHIVED'],[103,1005,1,'DRAFT'],
                       [104,1007,2,'PUBLISHED'],[105,None,None,None],[106,1008,1,'PUBLISHED']]},
     hints=['Раздели окно PARTITION BY DOC_ID.',
            'Задай все три поля ORDER BY внутри OVER, не только итоговую сортировку запроса.',
            'Фильтр RN = 1 добавь к ON внешнего LEFT JOIN, чтобы сохранить 105.'],
     solution=LATEST_SQL,
     solution_notes='Порядок внутри окна выбирает победителя, ORDER BY в конце лишь сортирует вывод. '
                    'У 102 последняя версия ARCHIVED, хотя раньше была публикация. '
                    'Документ 105 сохраняется внешним соединением. Синтаксис OLAP и доступность на старых уровнях Db2 сверяй с платформой.',
     checks=['Для 104 выбрана только 1007.', 'Для 102 выбран ARCHIVED, для 105 NULL.',
             'Различаю последнюю версию и последнюю опубликованную версию.'],sources=['olap','cte']),
dict(id='cte',title='5. Составной аудит: версии, владельцы и права',minutes='15–20',
     topics=['cte'],prerequisites=['aggregation','nulls','windows'],goal='Собрать проверяемый отчёт нарушений из небольших этапов.',
     explanation='Раздели проверку на независимые признаки: нет версии, нет активного владельца, нет активного читателя. '
                 'Документ может иметь сразу несколько проблем. Сохрани признаки отдельными колонками, чтобы оператор видел причину.',
     task='Верни только документы с хотя бы одной проблемой. Колонки: DOC_ID, NO_VERSION, NO_ACTIVE_OWNER, NO_ACTIVE_READ. '
          'Каждый признак — 0 или 1. Активный владелец — OWNER_ID, связанный с ACTIVE = Y. '
          'Активный читатель определяется как в занятии 3. Составь CTE с признаками и отдельный итоговый отбор.',
     expected={'columns':['DOC_ID','NO_VERSION','NO_ACTIVE_OWNER','NO_ACTIVE_READ'],
               'rows':[[103,0,1,1],[104,0,1,0],[105,1,0,1]]},
     hints=['Для версии достаточно EXISTS, нумерация здесь не требуется.',
            'Для владельца проверь NOT EXISTS по EMPLOYEE_ID = OWNER_ID и ACTIVE = Y.',
            'Сформируй CASE WHEN NOT EXISTS (...) THEN 1 ELSE 0 END для каждого признака; фильтр вынеси наружу.'],
     solution='''WITH flags AS (
    SELECT d.DOC_ID,
        CASE WHEN NOT EXISTS (
            SELECT 1 FROM ORB_VERSIONS v WHERE v.DOC_ID = d.DOC_ID
        ) THEN 1 ELSE 0 END AS NO_VERSION,
        CASE WHEN NOT EXISTS (
            SELECT 1 FROM ORB_EMPLOYEES e
            WHERE e.EMPLOYEE_ID = d.OWNER_ID AND e.ACTIVE = 'Y'
        ) THEN 1 ELSE 0 END AS NO_ACTIVE_OWNER,
        CASE WHEN NOT EXISTS (
            SELECT 1 FROM ORB_GRANTS g
            JOIN ORB_EMPLOYEES e ON e.EMPLOYEE_ID = g.EMPLOYEE_ID AND e.ACTIVE = 'Y'
            WHERE g.DOC_ID = d.DOC_ID AND g.ACCESS_CODE = 'READ'
        ) THEN 1 ELSE 0 END AS NO_ACTIVE_READ
    FROM ORB_DOCS d
)
SELECT DOC_ID, NO_VERSION, NO_ACTIVE_OWNER, NO_ACTIVE_READ
FROM flags
WHERE NO_VERSION = 1 OR NO_ACTIVE_OWNER = 1 OR NO_ACTIVE_READ = 1
ORDER BY DOC_ID;''',
     solution_notes='NULL-владелец 103 не совпадает ни с одним сотрудником, владелец 104 неактивен. '
                    '105 имеет активного владельца, но не имеет версии и активного читателя. '
                    'Здесь не нужны сложные соединения с сырыми дочерними таблицами. '
                    'Логическое выделение CTE само по себе не является обещанием конкретного плана выполнения.',
     checks=['Вернул ровно 103, 104, 105.', 'Каждый признак объясняется отдельным требованием.',
             'Не потерял документ с несколькими проблемами.'],sources=['cte','exists','sqlref']),
dict(id='dates',title='6. Интервал дат и проверка гипотезы об индексе',minutes='15–20',
     topics=['dates'],prerequisites=[],goal='Точно задать временной интервал и отделить результат запроса от предположения о производительности.',
     explanation='Для двух календарных дней удобно задать включённое начало и исключённое начало следующего дня. '
                 'Это не зависит от того, какие доли секунды поддерживает конкретный TIMESTAMP. '
                 'Использование индекса — отдельная проверяемая гипотеза, а не свойство, гарантированное текстом SELECT.',
     task='Найди опубликованные версии за 3 и 4 октября 2026: VERSION_ID, DOC_ID, CREATED_AT. '
          'Используй полуоткрытый интервал. В заметках предложи кандидат индекса по STATE и CREATED_AT '
          'и опиши, что проверишь в плане выполнения на своей платформе. Индекс создавать не требуется.',
     expected={'columns':['VERSION_ID','DOC_ID','CREATED_AT'],
               'rows':[[1002,101,'2026-10-03 00:00:00'],[1006,104,'2026-10-04 15:00:00'],[1007,104,'2026-10-04 15:00:00']]},
     hints=['Нижняя граница — 2026-10-03 00:00:00, верхняя — 2026-10-05 00:00:00.',
            'Сравнивай CREATED_AT напрямую: >= начало и < конец, отдельно отбирая STATE.',
            'Для обсуждения индекса рассмотрите (STATE, CREATED_AT); выбор зависит от статистики и объёма, на 8 строках сканирование может быть разумным.'],
     solution=DATES_SQL,
     solution_notes='Фильтр исключает архивную 1004 и черновую 1005, даже если их время внутри интервала. '
                    '1002 на нижней границе включена, 1008 ровно на верхней исключена. '
                    'Полуоткрытая верхняя граница не требует угадывать последнюю долю секунды 4 октября. '
                    'Кандидат (STATE, CREATED_AT) нужно проверять по реальному плану и статистике; автоматического ускорения не обещаем. '
                    'Команды EXPLAIN, доступ к планам и допустимый DDL различаются в LUW, z/OS и IBM i. '
                    'TIMESTAMP в этом наборе не содержит часового пояса; не подставляй сюда правила UTC без отдельного требования.',
     checks=['Получил 1002, 1006, 1007 и правильные времена.', 'Верхняя граница исключена.',
             'Записал способ проверки плана, а не утверждение о гарантированном индексе.'],sources=['sqlref','index','platform']),
]
BY_ID = {item['id']:item for item in LESSONS}


def expected_text(lesson):
    table=lesson['expected']
    return ' | '.join(table['columns'])+'\n'+'\n'.join(' | '.join('NULL' if cell is None else str(cell) for cell in row) for row in table['rows'])


def dataset_text():
    parts=[SETUP_GUIDE,'']
    for name,table in TABLES.items():
        parts += [name,' | '.join(column+' '+dtype for column,dtype in table['columns'])]
        parts += [' | '.join('NULL' if x is None else str(x) for x in row) for row in table['rows']]
        parts.append('')
    return '\n'.join(parts)
