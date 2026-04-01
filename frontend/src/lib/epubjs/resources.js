import { substitute } from "./utils/replacements";
import { createBase64Url, createBlobUrl, blob2base64 } from "./utils/core";
import Url from "./utils/url";
import mime from "./utils/mime";
import Path from "./utils/path";
import path from "path-webpack";

/**
 * Handle Package Resources
 * @class
 * @param {Manifest} manifest
 * @param {object} [options]
 * @param {string} [options.replacements="base64"]
 * @param {Archive} [options.archive]
 * @param {method} [options.resolver]
 */
class Resources {
  constructor(manifest, options) {
    this.settings = {
      replacements: (options && options.replacements) || "base64",
      archive: options && options.archive,
      resolver: options && options.resolver,
      request: options && options.request,
    };

    this.process(manifest);
  }

  /**
   * Process resources
   * @param {Manifest} manifest
   */
  process(manifest) {
    this.manifest = manifest;
    this.resources = Object.keys(manifest).map(function (key) {
      return manifest[key];
    });

    this.replacementUrls = [];
    this.imagePromises = new Map(); // href -> Promise<string|null>

    this.html = [];
    this.assets = [];
    this.css = [];

    this.urls = [];
    this.cssUrls = [];

    this.split();
    this.splitUrls();
  }

  /**
   * Split resources by type
   * @private
   */
  split() {
    // HTML
    this.html = this.resources.filter(function (item) {
      if (item.type === "application/xhtml+xml" || item.type === "text/html") {
        return true;
      }
    });

    // Exclude HTML
    this.assets = this.resources.filter(function (item) {
      if (item.type !== "application/xhtml+xml" && item.type !== "text/html") {
        return true;
      }
    });

    // Only CSS
    this.css = this.resources.filter(function (item) {
      if (item.type === "text/css") {
        return true;
      }
    });
  }

  /**
   * Convert split resources into Urls
   * @private
   */
  splitUrls() {
    // All Assets Urls
    this.urls = this.assets.map(
      function (item) {
        return item.href;
      }.bind(this),
    );

    // Css Urls
    this.cssUrls = this.css.map(function (item) {
      return item.href;
    });
  }

  /**
   * Create a url to a resource
   * @param {string} url
   * @return {Promise<string>} Promise resolves with url string
   */
  createUrl(url) {
    var parsedUrl = new Url(url);
    var mimeType = mime.lookup(parsedUrl.filename);

    if (this.settings.archive) {
      return this.settings.archive.createUrl(url, {
        base64: this.settings.replacements === "base64",
      });
    } else {
      if (this.settings.replacements === "base64") {
        return this.settings
          .request(url, "blob")
          .then((blob) => {
            return blob2base64(blob);
          })
          .then((blob) => {
            return createBase64Url(blob, mimeType);
          });
      } else {
        return this.settings.request(url, "blob").then((blob) => {
          return createBlobUrl(blob, mimeType);
        });
      }
    }
  }

  /**
   * Create blob urls for all the assets
   * @return {Promise}         returns replacement urls
   */
  replacements() {
    if (this.settings.replacements === "none") {
      return new Promise(
        function (resolve) {
          resolve(this.urls);
        }.bind(this),
      );
    }

    var imageMimes = new Set([
      "image/jpeg",
      "image/png",
      "image/gif",
      "image/webp",
      "image/svg+xml",
      "image/bmp",
      "image/tiff",
    ]);

    var nonImageJobs = [];
    var imageJobs = [];

    this.assets.forEach((item, i) => {
      if (imageMimes.has(item.type)) {
        imageJobs.push({ index: i, url: this.urls[i] });
      } else {
        nonImageJobs.push({ index: i, url: this.urls[i] });
      }
    });

    // Block on CSS/fonts only
    var replacements = nonImageJobs.map(({ url }) => {
      var absolute = this.settings.resolver(url);
      return this.createUrl(absolute).catch((err) => {
        console.error(err);
        return null;
      });
    });

    return Promise.all(replacements).then((results) => {
      this.replacementUrls = new Array(this.urls.length).fill(null);
      nonImageJobs.forEach(({ index }, i) => {
        if (typeof results[i] === "string") {
          this.replacementUrls[index] = results[i];
        }
      });

      // Record which indices are images (for on-demand fetch in substituteAsync)
      this._imageIndices = new Set(imageJobs.map(({ index }) => index));

      return this.replacementUrls;
    });
  }

  /**
   * Fetch a single image asset as a blob URL on demand.
   * Caches the promise so repeated calls for the same asset share one fetch.
   * @param  {number} index  index into this.urls / this.assets
   * @return {Promise<string|null>}
   */
  _fetchImage(index) {
    var href = this.urls[index];
    if (this.imagePromises.has(href)) {
      return this.imagePromises.get(href);
    }
    var absolute = this.settings.resolver(href);
    var promise = this.createUrl(absolute)
      .then((blobUrl) => {
        if (typeof blobUrl === "string") {
          this.replacementUrls[index] = blobUrl;
        }
        return blobUrl;
      })
      .catch(() => null);
    this.imagePromises.set(href, promise);
    return promise;
  }

  /**
   * Substitute urls in content, fetching blob URLs on demand for any
   * images referenced in this section's HTML.
   * @param  {string} content  serialized section HTML
   * @param  {string} [url]    section url for relative resolution
   * @return {Promise<string>} content with urls substituted
   */
  substituteAsync(content, url) {
    // Find images in this section that need fetching.
    // Check both the raw href (relative path like "image/0.jpg") and
    // the resolved relative URL, since content may contain either form.
    var relUrls = url ? this.relativeTo(url) : this.urls;
    var pending = [];

    this.urls.forEach((assetHref, i) => {
      if (this.replacementUrls[i]) return; // already resolved
      if (!this._imageIndices || !this._imageIndices.has(i)) return;
      // Match against raw href (relative) or resolved URL
      if (
        (assetHref && content.indexOf(assetHref) !== -1) ||
        (relUrls[i] && content.indexOf(relUrls[i]) !== -1)
      ) {
        pending.push(this._fetchImage(i));
      }
    });

    if (pending.length === 0) {
      return Promise.resolve(this.substitute(content, url));
    }

    return Promise.all(pending).then(() => {
      return this.substitute(content, url);
    });
  }

  /**
   * Replace URLs in CSS resources
   * @private
   * @param  {Archive} [archive]
   * @param  {method} [resolver]
   * @return {Promise}
   */
  replaceCss(archive, resolver) {
    var replaced = [];
    archive = archive || this.settings.archive;
    resolver = resolver || this.settings.resolver;
    this.cssUrls.forEach(
      function (href) {
        var replacement = this.createCssFile(href, archive, resolver).then(
          function (replacementUrl) {
            // switch the url in the replacementUrls
            var indexInUrls = this.urls.indexOf(href);
            if (indexInUrls > -1) {
              this.replacementUrls[indexInUrls] = replacementUrl;
            }
          }.bind(this),
        );

        replaced.push(replacement);
      }.bind(this),
    );
    return Promise.all(replaced);
  }

  /**
   * Create a new CSS file with the replaced URLs
   * @private
   * @param  {string} href the original css file
   * @return {Promise}  returns a BlobUrl to the new CSS file or a data url
   */
  createCssFile(href) {
    var newUrl;

    if (path.isAbsolute(href)) {
      return new Promise(function (resolve) {
        resolve();
      });
    }

    var absolute = this.settings.resolver(href);

    // Get the text of the css file from the archive
    var textResponse;

    if (this.settings.archive) {
      textResponse = this.settings.archive.getText(absolute);
    } else {
      textResponse = this.settings.request(absolute, "text");
    }

    // Get asset links relative to css file
    var relUrls = this.urls.map((assetHref) => {
      var resolved = this.settings.resolver(assetHref);
      var relative = new Path(absolute).relative(resolved);

      return relative;
    });

    if (!textResponse) {
      // file not found, don't replace
      return new Promise(function (resolve) {
        resolve();
      });
    }

    return textResponse.then(
      (text) => {
        // Replacements in the css text
        text = substitute(text, relUrls, this.replacementUrls);

        // Get the new url
        if (this.settings.replacements === "base64") {
          newUrl = createBase64Url(text, "text/css");
        } else {
          newUrl = createBlobUrl(text, "text/css");
        }

        return newUrl;
      },
      (err) => {
        // handle response errors
        return new Promise(function (resolve) {
          resolve();
        });
      },
    );
  }

  /**
   * Resolve all resources URLs relative to an absolute URL
   * @param  {string} absolute to be resolved to
   * @param  {resolver} [resolver]
   * @return {string[]} array with relative Urls
   */
  relativeTo(absolute, resolver) {
    resolver = resolver || this.settings.resolver;

    // Get Urls relative to current sections
    return this.urls.map(
      function (href) {
        var resolved = resolver(href);
        var relative = new Path(absolute).relative(resolved);
        return relative;
      }.bind(this),
    );
  }

  /**
   * Get a URL for a resource
   * @param  {string} path
   * @return {string} url
   */
  get(path) {
    var indexInUrls = this.urls.indexOf(path);
    if (indexInUrls === -1) {
      return;
    }
    if (this.replacementUrls.length) {
      return new Promise(
        function (resolve, reject) {
          resolve(this.replacementUrls[indexInUrls]);
        }.bind(this),
      );
    } else {
      return this.createUrl(path);
    }
  }

  /**
   * Substitute urls in content, with replacements,
   * relative to a url if provided
   * @param  {string} content
   * @param  {string} [url]   url to resolve to
   * @return {string}         content with urls substituted
   */
  substitute(content, url) {
    var relUrls;
    if (url) {
      relUrls = this.relativeTo(url);
    } else {
      relUrls = this.urls;
    }
    return substitute(content, relUrls, this.replacementUrls);
  }

  destroy() {
    this.settings = undefined;
    this.manifest = undefined;
    this.resources = undefined;
    this.replacementUrls = undefined;
    this.imagePromises = undefined;
    this.html = undefined;
    this.assets = undefined;
    this.css = undefined;

    this.urls = undefined;
    this.cssUrls = undefined;
  }
}

export default Resources;
