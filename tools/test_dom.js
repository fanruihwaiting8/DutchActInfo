/* Boots the real markup + app.js inside the jsc DOM shim and checks that the
   page actually renders and reacts to clicks. This catches runtime errors that
   the pure-logic tests in tools/test_app.js cannot see.

   jsc tools/dom_shim.js web/data.js web/i18n.js web/app.js tools/test_dom.js
*/
(function (global) {
  'use strict';

  var dom = global.__dom;
  var doc = global.document;
  var failures = 0;

  function check(name, condition) {
    if (condition) {
      print('ok   - ' + name);
    } else {
      print('FAIL - ' + name);
      failures += 1;
    }
  }

  function id(value) { return doc.getElementById(value); }
  function cards() { return id('results').querySelectorAll('.card'); }
  function hasHan(value) { return /[\u4e00-\u9fff]/.test(String(value)); }

  /* ------------------------------------------------------- initial render */

  var initial = cards();
  check('cards render on load', initial.length > 0);
  check('result summary is filled in', String(id('count').textContent).length > 0);
  check('empty notice is hidden while there are results', id('empty').hidden === true);
  check('every card shows a drive time', initial.every(function (card) {
    return card.querySelectorAll('.travel').length === 1;
  }));
  check('every card has a details button', initial.every(function (card) {
    return card.querySelectorAll('.detail-link').length === 1;
  }));
  check('no small-town card by default', initial.every(function (card) {
    return card.querySelectorAll('.tag-local').length === 0;
  }));
  check('document title is set', String(doc.title).length > 0);
  check('window label is filled in', String(id('window-label').textContent).indexOf('\u2026') < 0);
  check('footer timestamp is filled in', String(id('updated').textContent).length > 0);
  check('sources are listed', id('sources').querySelectorAll('a').length > 0);

  /* --------------------------------------------------------------- selects */

  check('province select is populated', id('province').childNodes.length > 5);
  check('city select is populated', id('city').childNodes.length > 20);

  /* ---------------------------------------------------------- travel chips */

  function chip(row, key, value) {
    return id(row).querySelectorAll('.chip').filter(function (node) {
      return node.getAttribute('data-' + key) === value;
    })[0];
  }

  check('1.5 hour chip is active by default', chip('travel-row', 'travel', 'ninety').classList.contains('active'));

  dom.click(chip('travel-row', 'travel', 'hour'));
  var hourCards = cards();
  check('1 hour filter still renders cards', hourCards.length > 0);
  check('1 hour filter marks its own chip active',
    chip('travel-row', 'travel', 'hour').classList.contains('active')
    && !chip('travel-row', 'travel', 'ninety').classList.contains('active'));

  dom.click(chip('travel-row', 'travel', 'all'));
  check('any distance shows at least as many cards', cards().length >= hourCards.length);

  /* -------------------------------------------------------- small-town flag */

  var box = id('include-local');
  box.checked = true;
  dom.change(box);
  check('small-town toggle re-renders', cards().length > 0);
  box.checked = false;
  dom.change(box);

  /* ------------------------------------------------------------ card click */

  var before = dom.opened.length;
  dom.click(cards()[0]);
  check('clicking a card opens the event page', dom.opened.length === before + 1
    && /^https?:/.test(dom.opened[dom.opened.length - 1]));

  /* --------------------------------------------------------- language swap */

  var englishTitle = String(doc.title);
  dom.click(id('lang-btn'));
  check('language button switches the title to Chinese',
    hasHan(doc.title) && String(doc.title) !== englishTitle);
  check('html lang attribute follows the language',
    String(doc.documentElement.getAttribute('lang')).indexOf('zh') === 0);
  check('cards re-render in Chinese', hasHan(cards()[0].querySelector('.detail-link').textContent));
  check('day headings are Chinese', hasHan(id('results').querySelector('.day-head').textContent));
  check('drive time line is Chinese', hasHan(cards()[0].querySelector('.travel').textContent));
  check('about radius text is Chinese and resolved',
    hasHan(id('about-radius').textContent)
    && String(id('about-radius').textContent).indexOf('{home}') < 0);
  check('selects keep their all-option label', hasHan(id('province').firstChild.textContent));

  dom.click(id('lang-btn'));
  check('language button switches back to English',
    !hasHan(doc.title) && String(doc.title) === englishTitle);

  /* ----------------------------------------------------------------- reset */

  dom.click(chip('travel-row', 'travel', 'hour'));
  dom.click(id('reset'));
  check('reset restores the 1.5 hour default',
    chip('travel-row', 'travel', 'ninety').classList.contains('active'));
  check('reset keeps cards on screen', cards().length > 0);

  print('');
  if (failures) {
    print(failures + ' DOM CHECK(S) FAILED');
    throw new Error('dom smoke test failed');
  }
  print('ALL DOM CHECKS PASSED');
}(typeof globalThis !== 'undefined' ? globalThis : this));