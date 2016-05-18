/** First install the convex-hull node package:
*
* $ npm install convex-hull
*
* Then convert this tiny script into a browser-ready file
* than makes the convex hull function reachable from CATMAID:
*
* $ browserify geometry-wrapper.js -o geometry.js
*
* The resulting geometry.js file is committed to CATMAID's git repository.
*/
window.GeometryTools = {
  // See: https://github.com/mikolalysenko/convex-hull
  convexHull: require("convex-hull"),

  // See: https://github.com/mikolalysenko/alpha-complex
  alphaComplex: require("alpha-complex"),

  // See: https://github.com/mikolalysenko/cell-orientation
  cellOrientation: require('cell-orientation'),

  // See: https://github.com/mikolalysenko/flip-orientation
  flipOrientation: require('flip-orientation'),

  // See: https://github.com/mikolalysenko/compare-cell
  compareCell: require('compare-cell'),
};
