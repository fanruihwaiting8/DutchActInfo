/* Smoke tests for web/app.js pure helpers.
   Run with macOS JavaScriptCore:
   /System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc \
     tools/jsc_shim.js web/data.js web/i18n.js web/app.js tools/test_app.js   */

var failures = 0;

function check(label, condition, extra) {
  if (condition) {
    print('ok   - ' + label);
  } else {
    failures += 1;
    print('FAIL - ' + label + (extra === undefined ? '' : ' :: ' + extra));
  }
}

var core = this.ActivityCore;
check('ActivityCore is exported', !!core);
if (!core) { throw new Error('ActivityCore missing'); }

/* ---------------------------------------------------------------- dates */

check('parseISO parses a valid date', core.parseISO('2026-11-07') !== null);
check('parseISO rejects junk', core.parseISO('not-a-date') === null);
check('formatDay renders weekday + month',
  core.formatDay('2026-10-31') === 'Saturday 31 October',
  core.formatDay('2026-10-31'));
check('formatRange collapses one-day ranges',
  core.formatRange('2026-10-31', '2026-10-31').indexOf('31 October') >= 0,
  core.formatRange('2026-10-31', '2026-10-31'));
check('formatRange shows both ends',
  core.formatRange('2026-10-30', '2026-11-01').indexOf('-') > 0,
  core.formatRange('2026-10-30', '2026-11-01'));
check('todayISO looks like a date', /^\d{4}-\d{2}-\d{2}$/.test(core.todayISO()), core.todayISO());

/* ---------------------------------------------------------------- dataset */

var data = this.ACTIVITY_DATA;
check('dataset is loaded', !!data && !!data.events && data.events.length > 0);

var entries = core.expand(data.events);
check('expand produces at least as many entries as events', entries.length >= data.events.length,
  entries.length + ' vs ' + data.events.length);
check('every entry carries a single date',
  entries.every(function (item) { return /^\d{4}-\d{2}-\d{2}$/.test(item.date); }));
check('every entry falls on Fri/Sat/Sun',
  entries.every(function (item) {
    var day = core.parseISO(item.date).getUTCDay();
    return day === 5 || day === 6 || day === 0;
  }));
check('entries are sorted by date',
  entries.every(function (item, index) {
    return index === 0 || entries[index - 1].date <= item.date;
  }));
check('every entry has a city and a province',
  entries.every(function (item) { return !!item.event.city && !!item.event.province; }));

/* ---------------------------------------------------------------- filters */

var context = {
  today: '2026-10-27',
  nextRange: core.nextWeekendDates(entries, '2026-10-27'),
  thisMonth: '2026-10',
  nextMonth: '2026-11'
};
check('nextWeekendDates returns a [from, to] range',
  context.nextRange.length === 2 && context.nextRange[0] <= context.nextRange[1],
  JSON.stringify(context.nextRange));

function state(extra) {
  var base = { q: '', when: 'all', cat: 'all', province: 'all', city: 'all', day: 'all' };
  for (var key in extra) { if (extra.hasOwnProperty(key)) { base[key] = extra[key]; } }
  return base;
}

var all = core.filterEntries(entries, state(), context);
check('empty filter keeps everything', all.length === entries.length);

var festivals = core.filterEntries(entries, state({ cat: 'festival' }), context);
check('category filter keeps only festivals',
  festivals.length > 0 && festivals.every(function (item) { return item.event.category === 'festival'; }),
  festivals.length);

var amsterdam = core.filterEntries(entries, state({ city: 'Amsterdam' }), context);
check('city filter keeps only Amsterdam',
  amsterdam.length > 0 && amsterdam.every(function (item) { return item.event.city === 'Amsterdam'; }),
  amsterdam.length);

var nh = core.filterEntries(entries, state({ province: 'Noord-Holland' }), context);
check('province filter keeps only Noord-Holland',
  nh.length > 0 && nh.every(function (item) { return item.event.province === 'Noord-Holland'; }),
  nh.length);

var sundays = core.filterEntries(entries, state({ day: '0' }), context);
check('day filter keeps only Sundays',
  sundays.length > 0 && sundays.every(function (item) {
    return core.parseISO(item.date).getUTCDay() === 0;
  }), sundays.length);

var nextWeekend = core.filterEntries(entries, state({ when: 'next' }), context);
check('next-weekend filter stays inside the computed range',
  nextWeekend.length > 0 && nextWeekend.every(function (item) {
    return item.date >= context.nextRange[0] && item.date <= context.nextRange[1];
  }), nextWeekend.length);

var thisMonth = core.filterEntries(entries, state({ when: 'month' }), context);
check('this-month filter stays inside 2026-10',
  thisMonth.length > 0 && thisMonth.every(function (item) {
    return item.date.slice(0, 7) === '2026-10';
  }));

var nextMonthOnly = core.filterEntries(entries, state({ when: 'nextmonth' }), context);
check('next-month filter stays inside 2026-11',
  nextMonthOnly.length > 0 && nextMonthOnly.every(function (item) {
    return item.date.slice(0, 7) === '2026-11';
  }));
check('month + next-month covers the whole window',
  thisMonth.length + nextMonthOnly.length === entries.length,
  thisMonth.length + '+' + nextMonthOnly.length + ' vs ' + entries.length);

var query = core.filterEntries(entries, state({ q: 'amsterdam' }), context);
check('free-text search is case-insensitive and hits the city',
  query.length > 0 && query.length <= entries.length, query.length);

var combo = core.filterEntries(entries, state({ cat: 'concert', province: 'Zuid-Holland', day: '6' }), context);
check('combined filters apply together',
  combo.length > 0 && combo.every(function (item) {
    return item.event.category === 'concert'
      && item.event.province === 'Zuid-Holland'
      && core.parseISO(item.date).getUTCDay() === 6;
  }), combo.length);

var none = core.filterEntries(entries, state({ q: 'zzzzz-no-such-activity' }), context);
check('impossible search returns nothing', none.length === 0, none.length);

/* ---------------------------------------------------------------- grouping */

var groups = core.groupByDate(all.slice(0, 200));
check('groupByDate returns non-empty groups', groups.length > 0);
check('groups are sorted and non-empty',
  groups.every(function (group, index) {
    return group.items.length > 0 && (index === 0 || groups[index - 1].date <= group.date);
  }));
check('grouping preserves the item count',
  groups.reduce(function (sum, group) { return sum + group.items.length; }, 0) === 200);

/* ------------------------------------------------------------ drive time */

check('dataset carries a home city', !!data.home && !!data.home.city, JSON.stringify(data.home));
check('every event has a travel tier and minutes',
  data.events.every(function (event) {
    return typeof event.travel === 'string' && typeof event.travel_minutes === 'number';
  }));
check('every event has a boolean local flag',
  data.events.every(function (event) { return typeof event.local === 'boolean'; }));

var withinHour = core.filterEntries(entries, state({ travel: 'hour' }), context);
check('1-hour filter keeps only near/hour tiers',
  withinHour.length > 0 && withinHour.every(function (item) {
    return item.event.travel === 'near' || item.event.travel === 'hour';
  }), withinHour.length);

var withinNinety = core.filterEntries(entries, state({ travel: 'ninety' }), context);
check('1.5-hour filter is a superset of the 1-hour filter',
  withinNinety.length >= withinHour.length && withinNinety.every(function (item) {
    return item.event.travel !== 'far' && item.event.travel !== 'unknown';
  }), withinNinety.length + ' vs ' + withinHour.length);

var noLocal = core.filterEntries(entries, state({ includeLocal: false }), context);
check('hiding small towns drops the local events',
  noLocal.every(function (item) { return !item.event.local; })
    && noLocal.length <= entries.length, noLocal.length + ' of ' + entries.length);

var recommended = core.filterEntries(entries, state({ travel: 'ninety', includeLocal: false }), context);
check('default view still has plenty to show', recommended.length > 100, recommended.length);

check('every event within 1.5 hours is at most 95 minutes away',
  withinNinety.every(function (item) { return item.event.travel_minutes <= 95; }));

/* ------------------------------------------------------------------ i18n */

var i18n = this.ACTIVITY_I18N;
check('i18n bundle is loaded with both languages', !!i18n && !!i18n.en && !!i18n.zh);
if (i18n && i18n.en && i18n.zh) {
  var missing = Object.keys(i18n.en).filter(function (key) { return i18n.zh[key] === undefined; });
  check('Chinese bundle covers every English key', missing.length === 0, missing.join(', '));
  var extra = Object.keys(i18n.zh).filter(function (key) { return i18n.en[key] === undefined; });
  check('Chinese bundle has no stray keys', extra.length === 0, extra.join(', '));
  check('both bundles agree on key types',
    Object.keys(i18n.en).every(function (key) { return typeof i18n.en[key] === typeof i18n.zh[key]; }));
  check('month and day tables are complete',
    i18n.zh.months.length === 12 && i18n.zh.days.length === 7
      && i18n.en.months.length === 12 && i18n.en.days.length === 7);
  check('travel text renders in Chinese',
    i18n.zh.travelText(21, 30, 'Den Haag').indexOf('Den Haag') >= 0,
    i18n.zh.travelText(21, 30, 'Den Haag'));
  check('about text has a home placeholder', i18n.zh.aboutRadius.indexOf('{home}') >= 0);
}

print('');
print(failures === 0 ? 'ALL TESTS PASSED' : failures + ' TEST(S) FAILED');
if (failures > 0) { throw new Error(failures + ' failing test(s)'); }