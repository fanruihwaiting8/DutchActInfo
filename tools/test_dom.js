/* Boots the real markup + app.js inside the jsc DOM shim and checks that the
   page actually renders and reacts to clicks. This catches runtime errors that
   the pure-logic tests in tools/test_app.js cannot see.

   jsc tools/dom_shim.js web/data.js web/i18n.js web/places.js web/app.js tools/test_dom.js
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

  /* -------------------------------------------------------- category chips */

  var CATS = ['festival', 'concert', 'comedy', 'expo', 'museum', 'seasonal'];
  check('every category has a chip', CATS.every(function (value) {
    return !!chip('cat-row', 'cat', value);
  }));

  CATS.forEach(function (value) {
    dom.click(chip('cat-row', 'cat', value));
    var shown = cards();
    check(value + ' chip keeps only matching cards', shown.every(function (card) {
      var badges = card.querySelectorAll('.badge');
      return badges.some(function (node) { return node.classList.contains(value); });
    }));
    check(value + ' chip shows the empty notice when nothing matches',
      (shown.length === 0) === (id('empty').hidden === false));
  });

  dom.click(chip('cat-row', 'cat', 'all'));
  check('all types chip restores the full list', cards().length > 0);

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

  /* ----------------------------------------------------------travel guide */

  function guides() {
    return cards().map(function (card) { return card.querySelector('.guide'); });
  }

  function distanceValue(text) {
    var raw = String(text);
    var found = raw.match(/(\d+(?:[.,]\d+)?)/);
    if (!found) { return null; }
    var value = parseFloat(found[1].replace(',', '.'));
    return raw.indexOf('km') >= 0 ? value * 1000 : value;
  }

  var guided = cards();
  check('every card carries exactly one travel guide', guided.every(function (card) {
    return card.querySelectorAll('.guide').length === 1;
  }));
  check('every guide has a summary and two advice lines', guides().every(function (box) {
    return box.querySelectorAll('summary').length === 1
      && box.querySelectorAll('.guide-line').length === 2;
  }));
  check('every guide links a transit route', guides().every(function (box) {
    var link = box.querySelectorAll('.guide-link')[0];
    return !!link && String(link.href).indexOf('travelmode=transit') > 0
      && String(link.href).indexOf('origin=') > 0;
  }));
  check('every guide links a parking search', guides().every(function (box) {
    var link = box.querySelectorAll('.guide-link')[1];
    return !!link && String(link.href).indexOf('/maps/search/') > 0;
  }));

  var listed = guides().filter(function (box) {
    return box.querySelectorAll('.parking-list').length === 1;
  });
  check('at least one guide lists real car parks', listed.length > 0);
  check('listed guides add the rate footnote', listed.every(function (box) {
    return box.querySelectorAll('.guide-note').length === 1;
  }));
  check('car parks run from nearest to furthest', listed.every(function (box) {
    var metres = box.querySelector('.parking-list').querySelectorAll('li').map(function (row) {
      return distanceValue(row.querySelector('.p-dist').textContent);
    });
    for (var i = 0; i < metres.length; i += 1) {
      if (metres[i] === null) { return false; }
      if (i > 0 && metres[i] < metres[i - 1] - 100) { return false; }
    }
    return true;
  }));
  check('every listed car park shows a distance, a name and a rate', listed.every(function (box) {
    return box.querySelector('.parking-list').querySelectorAll('li').every(function (row) {
      var meta = String(row.querySelector('.p-meta').textContent);
      return String(row.querySelector('.p-name').textContent).length > 0
        && /\d/.test(String(row.querySelector('.p-dist').textContent))
        && /\u20ac|free|price unknown/.test(meta);
    });
  }));

  var guideClicks = dom.opened.length;
  dom.click(guides()[0].querySelector('summary'));
  check('opening a guide does not open the event page', dom.opened.length === guideClicks);

  /* --------------------------------------------------------- postcode home */

  function travelText() {
    return id('results').querySelectorAll('.travel').map(function (node) {
      return String(node.textContent);
    }).join('|');
  }

  var defaultNote = String(id('home-note').textContent);
  var defaultTravel = travelText();

  dom.type(id('postcode'), '7511');
  check('typing alone leaves the centre untouched',
    travelText() === defaultTravel && id('home-note').classList.contains('hint') === true);

  dom.click(id('postcode-apply'));
  check('a confirmed postcode is accepted', id('home-note').classList.contains('bad') === false
    && String(id('home-note').textContent) !== defaultNote);
  check('the accepted postcode names its own town',
    String(id('home-note').textContent).toLowerCase().indexOf('enschede') > 0);
  check('drive times are recalculated from the new centre', travelText() !== defaultTravel);
  check('cards stay on screen after moving the centre', cards().length > 0);
  check('the new centre feeds the transit links',
    String(guides()[0].querySelectorAll('.guide-link')[0].href).indexOf('7511') > 0);

  var firstTravel = travelText();
  dom.type(id('postcode'), '1012');
  dom.press(id('postcode'), 'Enter');
  check('pressing Enter confirms the postcode too',
    travelText() !== firstTravel && id('home-note').classList.contains('bad') === false);

  dom.type(id('postcode'), '99');
  check('a half-typed postcode is not applied on its own',
    id('home-note').classList.contains('bad') === false);
  dom.click(id('postcode-apply'));
  check('a half-typed postcode is flagged once confirmed', id('home-note').classList.contains('bad') === true);

  dom.click(id('postcode-clear'));
  check('clearing the field empties the input', String(id('postcode').value) === '');
  check('clearing the field restores the default centre',
    id('home-note').classList.contains('bad') === false
    && String(id('home-note').textContent) === defaultNote);
  check('clearing the field restores the default drive times', travelText() === defaultTravel);

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