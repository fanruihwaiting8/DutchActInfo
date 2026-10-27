/* Minimal browser shim so web/data.js can be loaded by JavaScriptCore (jsc).
   web/data.js assigns to `window.ACTIVITY_DATA`; jsc only has the global object. */
this.window = this;