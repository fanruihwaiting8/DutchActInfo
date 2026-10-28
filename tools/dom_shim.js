/* Minimal DOM shim for JavaScriptCore (jsc) so web/app.js can be booted
   against the real web/index.html markup. Only the handful of DOM APIs that
   app.js touches is implemented. Run from the repository root:

   jsc tools/dom_shim.js web/data.js web/i18n.js web/app.js tools/test_dom.js
*/
(function (global) {
  'use strict';

  global.window = global;

  var VOID = { meta: 1, link: 1, input: 1, br: 1, img: 1, hr: 1, source: 1 };
  var SKIP_CONTENT = { script: 1, noscript: 1, style: 1 };

  /* ------------------------------------------------------------------ node */

  function Node(tag) {
    this.nodeType = tag ? 1 : 3;
    this.tagName = tag ? tag.toUpperCase() : '';
    this.attributes = {};
    this.childNodes = [];
    this.parentNode = null;
    this.listeners = {};
    this.id = '';
    this.text = '';
    this.value = '';
    this.hidden = false;
  }

  function textNode(value) {
    var node = new Node(null);
    node.text = value;
    return node;
  }

  Node.prototype.appendChild = function (child) {
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  };

  Node.prototype.removeChild = function (child) {
    var at = this.childNodes.indexOf(child);
    if (at >= 0) { this.childNodes.splice(at, 1); }
    child.parentNode = null;
    return child;
  };

  Node.prototype.setAttribute = function (name, value) {
    this.attributes[name] = String(value);
    if (name === 'id') { this.id = String(value); }
  };

  Node.prototype.getAttribute = function (name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name)
      ? this.attributes[name] : null;
  };

  Node.prototype.hasAttribute = function (name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name);
  };

  Node.prototype.addEventListener = function (type, handler) {
    if (!this.listeners[type]) { this.listeners[type] = []; }
    this.listeners[type].push(handler);
  };

  Node.prototype.showModal = function () { this.open = true; };

  Object.defineProperty(Node.prototype, 'className', {
    get: function () { return this.attributes['class'] || '';},
    set: function (value) { this.attributes['class'] = String(value); }
  });

  Object.defineProperty(Node.prototype, 'classList', {
    get: function () {
      var node = this;
      return {
        contains: function (name) { return classes(node).indexOf(name) >= 0; },
        add: function (name) {
          var list = classes(node);
          if (list.indexOf(name) < 0) { list.push(name); node.className = list.join(' '); }
        },
        remove: function (name) {
          node.className = classes(node).filter(function (c) { return c !== name; }).join(' ');
        },
        toggle: function (name, force) {
          if (force) { this.add(name); } else { this.remove(name); }
        }
      };
    }
  });

  function classes(node) {
    return (node.attributes['class'] || '').split(/\s+/).filter(Boolean);
  }

  Object.defineProperty(Node.prototype, 'textContent', {
    get: function () {
      if (this.nodeType === 3) { return this.text; }
      return this.childNodes.map(function (child) { return child.textContent; }).join('');
    },
    set: function (value) {
      this.childNodes = [];
      this.appendChild(textNode(String(value)));
    }
  });

  Object.defineProperty(Node.prototype, 'innerHTML', {
    get: function () { return this.textContent; },
    set: function () { this.childNodes = []; }
  });

  Object.defineProperty(Node.prototype, 'firstChild', {
    get: function () { return this.childNodes.length ? this.childNodes[0] : null; }
  });

  /* -------------------------------------------------------------- matching */

  function matches(node, selector) {
    if (node.nodeType !== 1) { return false; }
    var sel = selector.trim();
    if (sel.charAt(0) === '.') { return classes(node).indexOf(sel.slice(1)) >= 0; }
    if (sel.charAt(0) === '#') { return node.id === sel.slice(1); }
    if (sel.charAt(0) === '[') { return node.hasAttribute(sel.slice(1, -1)); }
    return node.tagName === sel.toUpperCase();
  }

  Node.prototype.querySelectorAll = function (selector) {
    var out = [];
    (function walk(node) {
      node.childNodes.forEach(function (child) {
        if (matches(child, selector)) { out.push(child); }
        walk(child);
      });
    }(this));
    return out;
  };

  Node.prototype.querySelector = function (selector) {
    var all = this.querySelectorAll(selector);
    return all.length ? all[0] : null;
  };

  Node.prototype.closest = function (selector) {
    var node = this;
    while (node) {
      if (matches(node, selector)) { return node; }
      node = node.parentNode;
    }
    return null;
  };

  /* ---------------------------------------------------------- html parsing */

  var ATTR = /([a-zA-Z0-9_:.-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;

  function parseAttributes(node, raw) {
    var match;
    ATTR.lastIndex = 0;
    while ((match = ATTR.exec(raw))) {
      var value = match[2] !== undefined ? match[2]
        : match[3] !== undefined ? match[3]
          : match[4] !== undefined ? match[4] : '';
      node.setAttribute(match[1], decode(value));
      if (match[1] === 'value') { node.value = decode(value); }
      if (match[1] === 'hidden') { node.hidden = true; }
    }
  }

  function decode(value) {
    return String(value)
      .replace(/&hellip;/g, '\u2026')
      .replace(/&middot;/g, '\u00b7')
      .replace(/&#(\d+);/g, function (_, code) { return String.fromCharCode(+code); })
      .replace(/\x26lt;/g, '\x3c')
      .replace(/\x26gt;/g, '\x3e')
      .replace(/\x26quot;/g, '\x22')
      .replace(/\x26#39;/g, '\x27')
      .replace(/\x26amp;/g, '\x26');
  }

  var TAG = /<(\/?)([a-zA-Z][a-zA-Z0-9-]*)((?:[^>"']|"[^"]*"|'[^']*')*)>/g;

  function parseHTML(html) {
    var root = new Node('#root');
    var stack = [root];
    var cursor = 0;
    var match;
    TAG.lastIndex = 0;
    while ((match = TAG.exec(html))) {
      if (match.index > cursor) {
        var raw = html.slice(cursor, match.index);
        if (raw.trim()) {
          stack[stack.length - 1].appendChild(textNode(decode(raw.replace(/\s+/g, ' '))));
        }
      }
      cursor = TAG.lastIndex;
      var tag = match[2].toLowerCase();
      if (match[1]) {
        for (var i = stack.length - 1; i > 0; i -= 1) {
          if (stack[i].tagName === tag.toUpperCase()) { stack.length = i; break; }
        }
        continue;
      }
      var node = new Node(tag);
      parseAttributes(node, match[3] || '');
      stack[stack.length - 1].appendChild(node);
      if (VOID[tag] || /\/\s*$/.test(match[3] || '')) { continue; }
      if (SKIP_CONTENT[tag]) {
        var close = html.toLowerCase().indexOf('</' + tag, cursor);
        if (close >= 0) {
          cursor = html.indexOf('>', close) + 1;
          TAG.lastIndex = cursor;
        }
        continue;
      }
      stack.push(node);
    }
    return root;
  }

  /* ------------------------------------------------------------- document */

  var source = readFile('web/index.html');
  var tree = parseHTML(source.replace(/<!--[\s\S]*?-->/g, '').replace(/<!DOCTYPE[^>]*>/i, ''));
  var htmlNode = tree.querySelector('html') || tree;

  var byId = {};
  htmlNode.querySelectorAll('[id]').forEach(function (node) { byId[node.id] = node; });

  var document = {
    readyState: 'complete',
    title: '',
    documentElement: htmlNode,
    body: htmlNode.querySelector('body') || htmlNode,
    listeners: {},
    getElementById: function (id) { return byId[id] || null; },
    querySelector: function (sel) { return htmlNode.querySelector(sel); },
    querySelectorAll: function (sel) { return htmlNode.querySelectorAll(sel); },
    createElement: function (tag) { return new Node(tag); },
    createTextNode: function (value) { return textNode(value); },
    addEventListener: function (type, handler) {
      if (!this.listeners[type]) { this.listeners[type] = []; }
      this.listeners[type].push(handler);
    }
  };

  global.document = document;
  global.navigator = { language: 'en-US' };

  var storage = {};
  global.localStorage = {
    getItem: function (key) {
      return Object.prototype.hasOwnProperty.call(storage, key) ? storage[key] : null;
    },
    setItem: function (key, value) { storage[key] = String(value); },
    removeItem: function (key) { delete storage[key]; }
  };

  var opened = [];
  global.open = function (url) { opened.push(url); return null; };

  /* Walk up the tree calling click handlers, like real event bubbling. */
  function click(node) {
    var event = { target: node, preventDefault: function () {} };
    var current = node;
    while (current) {
      (current.listeners && current.listeners.click || []).forEach(function (handler) {
        handler.call(current, event);
      });
      current = current.parentNode;
    }
  }

  function change(node) {
    var event = { target: node };
    var current = node;
    while (current) {
      (current.listeners && current.listeners.change || []).forEach(function (handler) {
        handler.call(current, event);
      });
      current = current.parentNode;
    }
  }

  function fire(type, node, props) {
    var event = { target: node, preventDefault: function () {} };
    if (props) {
      Object.keys(props).forEach(function (key) { event[key] = props[key]; });
    }
    var current = node;
    while (current) {
      (current.listeners && current.listeners[type] || []).forEach(function (handler) {
        handler.call(current, event);
      });
      current = current.parentNode;
    }
  }

  global.__dom = {
    Node: Node,
    parseHTML: parseHTML,
    document: document,
    click: click,
    change: change,
    fire: fire,
    type: function (node, value) { node.value = String(value); fire('input', node); },
    press: function (node, key) { fire('keydown', node, { key: key }); },
    opened: opened,
    refreshIds: function () {
      byId = {};
      htmlNode.querySelectorAll('[id]').forEach(function (node) { byId[node.id] = node; });
    }
  };
}(typeof globalThis !== 'undefined' ? globalThis : this));