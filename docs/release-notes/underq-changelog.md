# PyKX under q Changelog

This changelog provides updates from PyKX 2.0.0 and above, for information relating to versions of PyKX prior to this version see the changelog linked below.

!!! Note

	The changelog presented here outlines changes to PyKX when operating within a q environment specifically, if you require changelogs associated with PyKX operating within a Python environment see [here](./changelog.md).

## PyKX 2.0.0

### Additions

- Addition of `.pykx.qcallable` and `.pykx.pycallable` fucntions which allow wrapping of a foreign Python callable function returning the result as q or Python foreign respectively.
- Addition of `.pykx.version` allowing users to programatically access their version from a q process.
- Addition of `.pykx.debug` namespace containing copies of useful process initialisation information specific to usage within a q enviroment
- Addition of function `.pykx.debugInfo` which returns a string representation of useful information when debugging issues with the the use of PyKX within the q environment
- Added the ability for users to print the return of a `conversion` object

	```q
	q).pykx.print .pykx.topd ([]5?1f;5?1f)
	          x        x1
	0  0.613745  0.493183
	1  0.529481  0.578520
	2  0.691610  0.083889
	3  0.229662  0.195991
	4  0.691953  0.375638
	```

### Fixes and Improvements

- Application of object setting on a Python list returns generic null rather than wrapped foreign object.
- Use of environment variables relating to `PyKX under q` must use `"true"` as accepted value, previously any value set for such environment variables would be supported.
- Fixed an issue where invocation of `.pykx.print` would not return results to stdout.
- Fixed an issue where `hsym`/`Path` style objects could not be passed to Python functions

	```q
	q).pykx.eval["lambda x: x"][`:test]`
	`:test	
	```

- Resolution to memory leak incurred during invocation of `.pykx.*eval` functions relating to return of Python foreign objects to q.
- Fixed an issue where segmentation faults could occur for various function if non Python backed foreign objects are passed in place of Python backed foreign

	```q
	q).pykx.toq .pykx.util.load[(`foreign_to_q;1)]
	'Provided foreign object is not a Python object
	```

- Fixed an issue where segmentation faults could occur through repeated invocation of `.pykx.pyexec`

	```q
	q)do[1000;.pykx.pyexec"1+1"]
	```

- Removed the ability when using PyKX under q to allow users set reserved Python keywords to other values