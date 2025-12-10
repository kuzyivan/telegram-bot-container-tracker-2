{% extends "base.html" %}

{% block title %}Поезд {{ train.terminal_train_number }} — Logistrail{% endblock %}

{% block content %}
<div class="max-w-[98%] mx-auto px-2 py-8 animate-fade-in pb-20">
    
    <!-- Хлебные крошки и заголовок -->
    <div class="flex items-center gap-4 mb-8">
        <a href="/admin/trains" class="p-2 bg-white border border-mono-border rounded-xl text-mono-gray hover:text-mono-black transition">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"></path></svg>
        </a>
        <h1 class="text-3xl font-bold text-mono-black tracking-tight flex items-center gap-3">
            {{ train.terminal_train_number }}
            <span class="text-lg font-normal text-mono-gray font-mono">{{ train.rzd_train_number or '' }}</span>
        </h1>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        
        <!-- БЛОК 1: ДАТЫ И МАРШРУТ -->
        <div class="lg:col-span-2 bg-white p-6 rounded-2xl shadow-card border border-transparent flex flex-col justify-between">
            <form action="/admin/trains/{{ train.id }}/update_dates" method="POST" class="grid grid-cols-1 sm:grid-cols-3 gap-4">
                
                <div class="space-y-1.5">
                    <label class="text-xs font-bold text-mono-gray uppercase ml-1">Отправление</label>
                    <input type="date" name="departure_date" 
                           value="{{ train.departure_date }}" 
                           class="w-full bg-mono-bg border-transparent rounded-lg px-3 py-2 text-sm font-medium focus:bg-white focus:ring-2 focus:ring-mono-black transition">
                </div>

                <div class="space-y-1.5">
                    <label class="text-xs font-bold text-mono-gray uppercase ml-1">Прибытие</label>
                    <input type="date" name="arrival_date" 
                           value="{{ train.arrival_date }}" 
                           class="w-full bg-mono-bg border-transparent rounded-lg px-3 py-2 text-sm font-medium focus:bg-white focus:ring-2 focus:ring-mono-black transition">
                </div>

                <div class="flex items-end">
                    <button type="submit" class="w-full bg-mono-black text-white px-4 py-2 rounded-lg text-sm font-bold hover:bg-gray-800 transition">
                        Сохранить
                    </button>
                </div>
            </form>

            <!-- 🔥 ОПИСАНИЕ МАРШРУТА -->
            <div class="mt-6 pt-4 border-t border-mono-border">
                <div class="flex flex-wrap items-center gap-4 text-sm">
                    <!-- Станция отправления -->
                    <div class="flex items-center gap-2">
                        <div class="w-2.5 h-2.5 rounded-full bg-mono-gray/50"></div>
                        <span class="font-medium text-mono-gray">{{ train.last_known_station or 'Отправление' }}</span>
                    </div>
                    
                    <!-- Стрелка -->
                    <div class="text-mono-border">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"></path></svg>
                    </div>

                    <!-- Станция назначения -->
                    <div class="flex items-center gap-2">
                        <div class="w-2.5 h-2.5 rounded-full bg-mono-black"></div>
                        <span class="font-bold text-mono-black text-base">{{ train.destination_station or 'Назначение' }}</span>
                    </div>
                    
                    <!-- Перегруз -->
                    {% if train.overload_station_name %}
                    <div class="ml-auto flex items-center gap-2 bg-yellow-50 px-3 py-1 rounded-lg border border-yellow-100 text-yellow-800">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"></path></svg>
                        <span class="text-[10px] font-bold uppercase tracking-wider">Перегруз:</span>
                        <span class="font-bold text-sm">{{ train.overload_station_name }}</span>
                    </div>
                    {% endif %}
                </div>
            </div>
        </div>

        <!-- БЛОК 2: KPI ФИНАНСЫ -->
        <div class="bg-mono-black text-white p-6 rounded-2xl shadow-lg flex flex-col justify-between">
            <div>
                <p class="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">Финансы рейса (Net)</p>
                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <p class="text-[10px] text-gray-400 uppercase">Себестоимость</p>
                        <p class="text-lg font-mono">{{ "{:,.0f}".format(kpi.total_cost).replace(',', ' ') }}</p>
                    </div>
                    <div>
                        <p class="text-[10px] text-gray-400 uppercase">Продажа</p>
                        <p class="text-lg font-mono text-green-400">{{ "{:,.0f}".format(kpi.total_sales).replace(',', ' ') }}</p>
                    </div>
                </div>
            </div>
            <div class="mt-4 pt-4 border-t border-gray-700">
                <div class="flex justify-between items-end">
                    <span class="text-sm font-bold">Маржа (Чистая):</span>
                    <span class="text-2xl font-bold font-mono {{ 'text-green-400' if kpi.total_margin > 0 else 'text-red-400' }}">
                        {{ "{:,.0f}".format(kpi.total_margin).replace(',', ' ') }} ₽
                    </span>
                </div>
            </div>
        </div>
    </div>

    <!-- БЛОК 3: ТАБЛИЦА -->
    <div class="bg-white rounded-2xl shadow-card border border-transparent overflow-hidden flex flex-col">
        
        <!-- Панель действий -->
        <div class="px-6 py-4 border-b border-mono-border bg-white flex flex-col sm:flex-row justify-between items-center gap-4 sticky top-0 z-20">
            <h3 class="font-bold text-mono-black">Состав поезда <span class="ml-2 text-xs bg-mono-bg px-2 py-0.5 rounded border border-mono-border text-mono-gray">{{ containers|length }}</span></h3>
            
            <form action="/admin/trains/{{ train.id }}/apply_calculation" method="POST" class="flex items-center gap-2 w-full sm:w-auto">
                <select name="calculation_id" required class="bg-white border border-mono-border text-sm rounded-xl py-2 px-3 focus:ring-2 focus:ring-mono-black outline-none w-full sm:w-64 cursor-pointer hover:bg-mono-bg transition">
                    <option value="" disabled selected>Применить Расчет (Себестоимость)</option>
                    {% for calc in calculations %}
                    <option value="{{ calc.id }}">{{ calc.title }} ({{ calc.container_type }}) - {{ "{:,.0f}".format(calc.total_cost) }}</option>
                    {% endfor %}
                </select>
                
                <div id="hidden-inputs-container"></div>

                <button type="button" onclick="submitBulkCalc()" class="bg-mono-black text-white px-4 py-2 rounded-xl text-sm font-bold hover:bg-gray-800 transition shadow-sm whitespace-nowrap">
                    Применить
                </button>
            </form>
        </div>

        <div class="overflow-x-auto w-full">
            <table class="w-full text-sm text-left border-collapse" id="containersTable">
                <thead class="bg-mono-bg text-mono-gray text-[10px] uppercase font-bold tracking-wider sticky top-[73px] z-10 shadow-sm">
                    <!-- Заголовки -->
                    <tr>
                        <th class="px-4 py-3 w-10 text-center bg-mono-bg">
                            <input type="checkbox" onclick="toggleAll(this)" class="rounded text-mono-black focus:ring-mono-black cursor-pointer">
                        </th>
                        <th class="px-4 py-3 bg-mono-bg">Контейнер</th>
                        <th class="px-4 py-3 bg-mono-bg">Клиент</th>
                        
                        <!-- 🔥 ИЗМЕНЕНИЕ: Заголовок "Размер" -->
                        <th class="px-4 py-3 text-center bg-mono-bg">Размер</th>
                        
                        <th class="px-4 py-3 text-right bg-mono-bg">Себест. (с НДС)</th>
                        <th class="px-4 py-3 text-right w-40 bg-mono-bg">Продажа (с НДС)</th>
                        
                        <th class="px-4 py-3 text-right bg-mono-bg cursor-pointer hover:text-mono-black transition select-none group" onclick="sortTable('margin')">
                            <div class="flex items-center justify-end gap-1">
                                Маржа (Net)
                                <span class="text-gray-400 group-hover:text-mono-black">↕</span>
                            </div>
                        </th>
                        
                        {% if user.role == 'admin' %}
                        <th class="px-4 py-3 text-center bg-mono-bg"></th>
                        {% endif %}
                    </tr>
                    
                    <!-- 🔥 СТРОКА ФИЛЬТРАЦИИ -->
                    <tr class="bg-white border-b border-mono-border">
                        <th class="px-4 py-2"></th>
                        <th class="px-4 py-2">
                            <input type="text" id="filterContainer" onkeyup="filterTable()" placeholder="Поиск..." 
                                   class="w-full px-2 py-1 text-xs border border-mono-border rounded focus:outline-none focus:border-mono-black">
                        </th>
                        <th class="px-4 py-2">
                            <input type="text" id="filterClient" onkeyup="filterTable()" placeholder="Фильтр по клиенту" 
                                   class="w-full px-2 py-1 text-xs border border-mono-border rounded focus:outline-none focus:border-mono-black">
                        </th>
                        <!-- 🔥 ИЗМЕНЕНИЕ: Фильтр размера -->
                        <th class="px-4 py-2">
                            <input type="text" id="filterSize" onkeyup="filterTable()" placeholder="20/40" 
                                   class="w-full px-2 py-1 text-xs border border-mono-border rounded text-center focus:outline-none focus:border-mono-black">
                        </th>
                        <th colspan="4"></th>
                    </tr>
                </thead>
                
                <tbody class="divide-y divide-mono-border bg-white" id="tableBody">
                    {% for item in containers %}
                    <!-- 
                        🔥 ИЗМЕНЕНИЕ: data-size вместо data-type 
                    -->
                    <tr class="hover:bg-mono-bg transition group container-row" 
                        data-client="{{ item.tc.client or '' }}" 
                        data-container="{{ item.tc.container_number }}"
                        data-size="{{ item.size }}" 
                        data-margin="{{ item.margin }}">
                        
                        <td class="px-4 py-3 text-center">
                            <input type="checkbox" name="selected_containers" value="{{ item.tc.id }}" class="container-checkbox rounded text-mono-black focus:ring-mono-black cursor-pointer">
                        </td>
                        <td class="px-4 py-3 font-mono font-bold text-mono-black">
                            {{ item.tc.container_number }}
                        </td>
                        <td class="px-4 py-3 text-xs text-mono-dark max-w-[200px] truncate" title="{{ item.tc.client }}">
                            {{ item.tc.client or '—' }}
                        </td>
                        
                        <!-- 🔥 ИЗМЕНЕНИЕ: Вывод размера (item.size) -->
                        <td class="px-4 py-3 text-center text-xs font-bold text-mono-black">
                            <span class="bg-mono-bg border border-mono-border px-1.5 py-0.5 rounded">{{ item.size }}</span>
                        </td>
                        
                        <!-- Себестоимость с НДС (x1.2) -->
                        <td class="px-4 py-3 text-right font-mono text-xs text-mono-gray">
                            {{ "{:,.0f}".format(item.cost * 1.2).replace(',', ' ') }}
                        </td>
                        
                        <!-- Продажа -->
                        <td class="px-4 py-3 text-right">
                            <div class="flex items-center justify-end gap-1">
                                <input type="number" 
                                       name="sales_price" 
                                       value="{{ item.sale }}" 
                                       step="100"
                                       class="w-24 bg-mono-bg border-transparent rounded px-2 py-1 text-right text-sm font-bold focus:bg-white focus:ring-2 focus:ring-mono-black outline-none transition"
                                       hx-post="/admin/trains/container/{{ item.tc.id }}/update_finance"
                                       hx-trigger="change"
                                       hx-target="#margin-{{ item.tc.id }}"
                                       hx-swap="innerHTML"
                                       title="Введите цену БЕЗ НДС">
                                <span class="text-[10px] text-gray-400">+НДС</span>
                            </div>
                        </td>
                        
                        <!-- Маржа Чистая (Net) -->
                        <td class="px-4 py-3 text-right font-mono text-sm" id="margin-{{ item.tc.id }}">
                            <span class="font-bold {{ 'text-green-600' if item.margin > 0 else 'text-red-600' }}">
                                {{ "{:,.0f}".format(item.margin).replace(',', ' ') }}
                            </span>
                        </td>
                        
                        {% if user.role == 'admin' %}
                        <td class="px-4 py-3 text-center">
                            <form action="/admin/trains/{{ train.id }}/remove_container" method="POST" onsubmit="return confirm('Убрать из поезда?')">
                                <input type="hidden" name="tc_id" value="{{ item.tc.id }}">
                                <button type="submit" class="text-gray-300 hover:text-red-500 transition">
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                                </button>
                            </form>
                        </td>
                        {% endif %}
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- Admin: Добавить контейнер вручную -->
    {% if user.role == 'admin' %}
    <div class="mt-8 bg-mono-bg p-6 rounded-2xl border border-mono-border">
        <h3 class="text-sm font-bold text-mono-gray uppercase tracking-wider mb-4">Ручное добавление контейнера</h3>
        <form action="/admin/trains/{{ train.id }}/add_container" method="POST" class="flex gap-4">
            <input type="text" name="container_number" placeholder="Номер контейнера (AAAA1234567)" required
                   class="flex-1 bg-white border-transparent rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-mono-black outline-none uppercase font-mono">
            <button type="submit" class="bg-mono-black text-white px-6 py-3 rounded-xl font-bold text-sm hover:bg-gray-800 transition">
                Добавить
            </button>
        </form>
    </div>
    {% endif %}

</div>

<script>
    function toggleAll(source) {
        document.querySelectorAll('.container-checkbox').forEach(cb => cb.checked = source.checked);
    }

    function submitBulkCalc() {
        const checkboxes = document.querySelectorAll('.container-checkbox:checked');
        if (checkboxes.length === 0) {
            alert("Выберите контейнеры!");
            return;
        }
        
        const container = document.getElementById('hidden-inputs-container');
        container.innerHTML = '';
        
        checkboxes.forEach(cb => {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'selected_containers';
            input.value = cb.value;
            container.appendChild(input);
        });
        
        container.closest('form').submit();
    }

    // --- ФИЛЬТРАЦИЯ (Обновлено для Size) ---
    function filterTable() {
        const filterContainer = document.getElementById('filterContainer').value.toUpperCase();
        const filterClient = document.getElementById('filterClient').value.toUpperCase();
        const filterSize = document.getElementById('filterSize').value.toUpperCase(); // <-- Ищем по filterSize
        
        const rows = document.querySelectorAll('.container-row');
        
        rows.forEach(row => {
            const container = row.getAttribute('data-container').toUpperCase();
            const client = row.getAttribute('data-client').toUpperCase();
            const size = row.getAttribute('data-size').toUpperCase(); // <-- data-size
            
            const matchContainer = container.includes(filterContainer);
            const matchClient = client.includes(filterClient);
            const matchSize = size.includes(filterSize); // <-- Проверка размера
            
            if (matchContainer && matchClient && matchSize) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    }

    // --- СОРТИРОВКА ПО МАРЖЕ ---
    let sortDirection = 1;

    function sortTable(key) {
        const tbody = document.getElementById('tableBody');
        const rows = Array.from(tbody.querySelectorAll('tr'));

        rows.sort((a, b) => {
            const valA = parseFloat(a.getAttribute(`data-${key}`)) || 0;
            const valB = parseFloat(b.getAttribute(`data-${key}`)) || 0;
            return (valA - valB) * sortDirection;
        });

        sortDirection *= -1;
        rows.forEach(row => tbody.appendChild(row));
    }
</script>
{% endblock %}