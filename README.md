# labs

Containerlab labs used for the blog posts in `../blog`.

| Lab | Role |
|-----|------|
| [`isis_interop`](isis_interop/README.md) | Five nodes, one SR OS vSIM border. Shows that an L1 router keeps or drops the default route on Nokia SR OS, Junos and FRR when the border LSP carries the attached bit and the overload bit. Lab of the post `isis-35-years-two-bits.md`. |
| [`isis_interop_drain`](isis_interop_drain/README.md) | Thirteen nodes, one border per vendor (SR-SIM, Junos, FRR). Tests how each vendor sets ATT and OL with overload and max-metric, and the RFC 5305 metric 16777215. The `two_exit` lab drains one of three borders in one area. Lab of the post `isis-draining-three-vendors.md`. |
