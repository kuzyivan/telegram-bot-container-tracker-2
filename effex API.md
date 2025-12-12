## API authentication

Каждая система effex – изолированный по данным и коду инстанс. В двухбуквенных кодах языка можно использовать значения из таблицы ниже, от этого зависит язык ответа и формат дат. Запросы можно отправлять методом GET или POST, если нет прямого указания на конкретный метод.

URI API – [https://\*.effex.ru/en/api](https://*.effex.ru/en/api)

| Code | Language |
| :---- | :---- |
| cn | 漢語 |
| de | Deutsch |
| en | English |
| es | Español |
| fr | Français |
| hi | हिन्दी |
| ko | 한국어 |
| nl | Nederlands |
| ru | Русский |
| tr | Türkçe |

Для начала работы необходимо получить от [support@effex.ru](mailto:support@effex.ru) токен, представляющий собой строку из 32 символов (буквы английского алфавита в разном регистре и цифры). Через токен сервис понимает, с какой площадкой и клиентом вы работаете.

При использовании любого метода API сервис будет содержать в ответе переменную status \= success / error. В случае error в переменной message будет причина ошибки.

| Message | Description |
| :---- | :---- |
| Invalid token | Забыли или передаете неверный токен |
| Frequency limit | Превышение частоты запросов, сейчас это 10 запросов в минуту и 180 запросов в час |
| Unknown method | Забыли или передаете неверный метод |
| Missing mandatory parameters | Отсутствуют обязательные параметры запроса |

## 

## method=container.items

Получение информации об имеющихся на терминале контейнерах клиента.

#### Request / Запрос

| Name | Type | Example |
| :---- | :---- | :---- |
| token | string\* | fQuq0Oils06PmEAys32m2JvG8negl3xm |
| method | string\* | container.items |

#### Response / Ответ

| Name | Type | Example |
| :---- | :---- | :---- |
| status | string | success |
| items | json | \[   {...}, сведения о контейнере   {...}, сведения о контейнере … \] |

container

| Name | Type | Description |
| :---- | :---- | :---- |
| id | int | наш id контейнера |
| customer | string | клиент |
| stock | string | сток |
| destination | string | станция назначения |
| destination\_id | int | ЕСР код станции назначения |
| depot | string | терминал |
| container | string | номер контейнера |
| container\_year | int | год изготовления контейнера |
| cooler | string | марка холодильного агрегат |
| cooler\_model | string | модель агрегата |
| cooler\_year | string | год изготовления агрегата |
| color | string | цвет контейнера |
| temperature | int | температурный режим |
| ventilation | int | вентиляция |
| gatein | string | дата приема в национальном формате |
| gatein\_timestamp | int | дата приема в unix timestamp |
| gateout | string | дата выдачи в национальном формате |
| gateout\_timestamp | int | дата выдачи в unix timestamp |
| type | string | iso тип |
| size | string | размер |
| special | string | род контейнера |
| capacity | int | грузоподъемность |
| tare | int | тара |
| state | string | статус по ремонту |
| cargo | string | статус по грузу |
| cargo\_id | enum\[1, 2\] | 1 – порожний 2 – груженый |
| customs | string | таможенный режим |
| danger | string | класс опасности груза |
| danger\_id | int | код класса опасности груза |
| plug | int | необходимость подключения к стационарной электросети |
| net | float | нетто |
| gross | float | брутто |
| gross2 | float | брутто терминала, завес при приеме |
| seal | string\[\] | ЗПУ (пломбы) массивом строк |
| seal\_damage | int | признак повреждения или несоответствия |

## 

## method=events

Получение информации об операциях с контейнерами на терминале. С опциональным параметром date в формате краткой даты или метки времени Unix метод выдает все события выбранных суток. Без него – события в режиме последовательного чтения, накопившиеся с предыдущего запроса.

#### Request / Запрос

| Name | Type | Example |
| :---- | :---- | :---- |
| token | string\* | fQuq0Oils06PmEAys32m2JvG8negl3xm |
| method | string\* | events |
| date | string|int | 01.09.2025, 1756674000 |
| limit | int | 1000 |

#### Response / Ответ

| Name | Type | Example |
| :---- | :---- | :---- |
| status | string | success |
| items | json | \[   {     "action": create / delete,     "container": {...}, сведения о контейнере     "operation": {...} сведения об операции   },   {     "action": create / delete,     "container": {...}, сведения о контейнере     "operation": {...} сведения об операции   }, … \] |

container

Описание полей идентично container.items

operation

| Name | Type | Description |
| :---- | :---- | :---- |
| id | int | наш id операции |
| direction | enum\[in, out\] | in – прием / начало, out – выдача / конец |
| type | string | тип операции |
| type\_id | int | тип операции, расшифровка key-value ниже |
| actual\_date | string | дата операции в национальном формате |
| actual\_date\_timestamp | int | дата операции в unix timestamp |
| reference | string | номер заказа, букинг, релиз |
| remark | string | примечание |
| *type \= 1, Автотягач type \= 7, Перестановка* |  |  |
| car | string | номер авто |
| driver | string | водитель |
| *type \= 2, поезд* |  |  |
| road | string | дорога отправления / назначения |
| station | string | станция отправления / назначения |
| station\_id | int | код станции ЕСР |
| train\_type | string | тип подачи / отправки |
| platform | string | номер вагона |
| platform\_type | string | род вагона |
| *type \= 3, Судно* |  |  |
| *type \= 4, ЗТК* |  |  |
| customs\_date | string | подача документов в ТО |
| declaration | string | способ декларирования |
| *type \= 5, СВХ* |  |  |
| *type \= 6, Таможенный досмотр* |  |  |
| appoint\_date | string | назначение досмотра |
| excess | enum\[0,1\] | превышение веса места |
| volume | int | объем работ |
| *type \= 8, Передача* |  |  |
| *type \= 9, Склад* |  |  |
| *type \= 10, PTI* |  |  |
| pti\_status | string | результат |
| temperature | int | выставленная температура |
| *type \= 11, Ветеринарный досмотр* |  |  |
| *type \= 12, Электросеть* |  |  |
| *type \= 14, Мониторинг* |  |  |
| monitoring\_status | string | результат |
| temperature | float | фактическая температура |
| *type \= 15, Подключение* |  |  |
| *type \= 16, Взвешивание* |  |  |
| *type \= 17, Выставление* |  |  |
| *type \= 18, Грузовые работы* |  |  |
| crossdocking\_type | string | тип работ |
| excess | enum\[0,1\] | превышение веса места |
| volume | int | объем работ |
| *type \= 19, Мойка* |  |  |
| washing\_type | string | тип работ |
| *type \= 20, Обогрев* |  |  |
| heating\_type | string | тип теплоносителя |

## 

## method=events.reset

Перед вызовом метода events можно задать дату, начиная с которой в режиме последовательного чтения будут возвращаться события. Обязательный параметр метода — date в формате короткой даты или в виде метки времени Unix.

#### Request / Запрос

| Name | Type | Example |
| :---- | :---- | :---- |
| token | string\* | fQuq0Oils06PmEAys32m2JvG8negl3xm |
| method | string\* | events.reset |
| date | string|int\* | 01.09.2025, 1756674000 |

#### Response / Ответ

| Name | Type | Example |
| :---- | :---- | :---- |
| status | string | success |
| item | int | 1 |

## 

## method=uploads.container

Получение файлов из карточки контейнера.

#### Request / Запрос

| Name | Type | Example |
| :---- | :---- | :---- |
| token | string\* | fQuq0Oils06PmEAys32m2JvG8negl3xm |
| method | string\* | uploads.container |
| item | int\* | наш id контейнера |

#### Response / Ответ

| Name | Type | Example |
| :---- | :---- | :---- |
| status | string | success |
| items | json | \[   {     "id": 7547811,     "name": "inspect\_0.jpg",     "time": "18/05/2025 12:49",     "base64": "..."   },   {     "id": 7547813,     "name": "inspect\_1.jpg",     "time": "18/05/2025 12:49",     "base64": "..."   },   …   \] } |

## 

## 

## method=arrival.create

Создание заявки на сдачу контейнера на терминал.

#### Request / Запрос

| Name | Type | Example |
| :---- | :---- | :---- |
| token | string\* | fQuq0Oils06PmEAys32m2JvG8negl3xm |
| method | string\* | arrival.create |
| container | string\* | TEST1234567 |
| beg\_date | string\* | 19.05.2025 |
| end\_date | string | 20.05.2025 |
| cargo | enum\[1, 2\] | 1 – порожний 2 – груженый |
| car | string | X123XX77 |
| driver\[name\] | string | Иванов Иван Иванович |

#### Response / Ответ

| Name | Type | Example |
| :---- | :---- | :---- |
| status | string | success |
| item | int | 12345 |

## 

## method=arrival.delete

Удаление заявки на сдачу контейнера на терминал.

#### Request / Запрос

| Name | Type | Example |
| :---- | :---- | :---- |
| token | string\* | fQuq0Oils06PmEAys32m2JvG8negl3xm |
| method | string\* | arrival.delete |
| item | int\* | 12345 |

#### Response / Ответ

| Name | Type | Example |
| :---- | :---- | :---- |
| status | string | success |
| item | int | 12345 |

## 

## method=dispatch.create

Создание заявки на номерную выдачу контейнера с терминала.

#### Request / Запрос

| Name | Type | Example |
| :---- | :---- | :---- |
| token | string\* | fQuq0Oils06PmEAys32m2JvG8negl3xm |
| method | string\* | dispatch.create |
| container | string\* | TEST1234567 |
| beg\_date | string\* | 19.05.2025 |
| end\_date | string | 20.05.2025 |
| car | string | X123XX77 |
| driver\[name\] | string | Иванов Иван Иванович |
| driver\[series\] | string | 4606 |
| driver\[number\] | string | 616796 |
| driver\[issued\] | string | 29.11.2003 |

#### Response / Ответ

| Name | Type | Example |
| :---- | :---- | :---- |
| status | string | success |
| item | int | 12345 |

## 

## method=dispatch.delete

Удаление заявки на выдачу контейнера с терминала.

#### Request / Запрос

| Name | Type | Example |
| :---- | :---- | :---- |
| token | string\* | fQuq0Oils06PmEAys32m2JvG8negl3xm |
| method | string\* | dispatch.delete |
| item | int\* | 12345 |

#### Response / Ответ

| Name | Type | Example |
| :---- | :---- | :---- |
| status | string | success |
| item | int | 12345 |

## method=barrier.arrival

СКУД запрашивает у системы терминала сведения о номерах автомобилей, допущенных к въезду для сдачи контейнеров.

#### Request / Запрос

| Name | Type | Example |
| :---- | :---- | :---- |
| token | string\* | fQuq0Oils06PmEAys32m2JvG8negl3xm |
| method | string\* | barrier.arrival |

#### Response / Ответ

| Name | Type | Example |
| :---- | :---- | :---- |
| status | string | success |
| items | json | \["E048XM199","C883BE977",...\] |

## method=barrier.dispatch

СКУД запрашивает у системы терминала сведения о номерах автомобилей, допущенных к въезду для выдачи контейнеров.

#### Request / Запрос

| Name | Type | Example |
| :---- | :---- | :---- |
| token | string\* | fQuq0Oils06PmEAys32m2JvG8negl3xm |
| method | string\* | barrier.dispatch |

#### Response / Ответ

| Name | Type | Example |
| :---- | :---- | :---- |
| status | string | success |
| items | json | \["E048XM199","C883BE977",...\] |

## method=barrier.pass

СКУД передает системе терминала сообщение о въезде автомобиля для активации сервисов самообслуживания водителя.

#### Request / Запрос

| Name | Type | Example |
| :---- | :---- | :---- |
| token | string\* | fQuq0Oils06PmEAys32m2JvG8negl3xm |
| method | string\* | barrier.pass |
| car | string\* | B235CX799 |

#### Response / Ответ

| Name | Type | Example |
| :---- | :---- | :---- |
| status | string | success |
| item | int | 1 |

## 

## method=barrier.check

СКУД запрашивает у системы терминала сведения о действительности QR-кода на пропуске или акте. Например, стойка шлагбаума может быть оборудована считывателем, который инициирует данный запрос и управляет исполнительными устройствами — светофором и стрелой шлагбаума.

#### Request / Запрос

| Name | Type | Example |
| :---- | :---- | :---- |
| token | string\* | fQuq0Oils06PmEAys32m2JvG8negl3xm |
| method | string\* | barrier.check |
| hash | string\* | f4223e56d530979a3e345873b91fb27c |

#### Response / Ответ

| Name | Type | Example |
| :---- | :---- | :---- |
| status | string | success |
| items | int | 1 |

