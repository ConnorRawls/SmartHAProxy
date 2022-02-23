#ifndef _HAPROXY_HTTPCLIENT_T_H
#define _HAPROXY_HTTPCLIENT_T_H

#include <haproxy/http-t.h>

struct httpclient {
	struct {
		struct ist url;                /* URL of the request */
		enum http_meth_t meth;       /* method of the request */
		struct buffer buf;             /* output buffer */
	} req;
	struct {
		struct ist vsn;
		uint16_t status;
		struct ist reason;
		struct http_hdr *hdrs;         /* headers */
		struct buffer buf;             /* input buffer */
	} res;
	struct {
		/* callbacks used to receive the response, if not set, the IO
		 * handler will consume the data without doing anything */
		void (*res_stline)(struct httpclient *hc);          /* start line received */
		void (*res_headers)(struct httpclient *hc);         /* headers received */
		void (*res_payload)(struct httpclient *hc);         /* payload received */
		void (*res_end)(struct httpclient *hc);             /* end of the response */
	} ops;
	struct sockaddr_storage dst;          /* destination address */
	struct appctx *appctx;                /* HTTPclient appctx */
	void *caller;                         /* ptr of the caller */
};

/* States of the HTTP Client Appctx */
enum {
	HTTPCLIENT_S_REQ = 0,
	HTTPCLIENT_S_RES_STLINE,
	HTTPCLIENT_S_RES_HDR,
	HTTPCLIENT_S_RES_BODY,
	HTTPCLIENT_S_RES_END,
};


#endif /* ! _HAPROXY_HTTCLIENT__T_H */
