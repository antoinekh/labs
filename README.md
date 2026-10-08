# labs

Network labs, mostly [containerlab](https://containerlab.dev). Some of them are used in the posts of [blog.antoinekh.dev](https://blog.antoinekh.dev/).

| Lab | Role |
|-----|------|
| [`isis_interop`](isis_interop/README.md) | Five nodes, one SR OS vSIM border. Shows that an L1 router keeps or drops the default route on Nokia SR OS, Junos and FRR when the border LSP carries the attached bit and the overload bit. Lab of the post [35 years of IS-IS, and vendors still disagree on two bits](https://blog.antoinekh.dev/posts/isis-35-years-two-bits/). |
| [`isis_interop_drain`](isis_interop_drain/README.md) | Thirteen nodes, one border per vendor (SR-SIM, Junos, FRR). Tests how each vendor sets ATT and OL with overload and max-metric, and the RFC 5305 metric 16777215. The `two_exit` lab drains one of three borders in one area. Lab of the post [Draining an IS-IS router: three vendors, three LSPs, and a bug in FRR](https://blog.antoinekh.dev/posts/isis-draining-three-vendors/). |
