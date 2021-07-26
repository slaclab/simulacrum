# SLAC Developer setup

## Bmad Production Environment

The current version of the Bmad distribution can be enabled with:

```bash
source /usr/local/lcls/package/bmad_distributions/enable
``` 


### Python

The standard Python 3.7 environment is enabled with:
```bash
source /usr/local/lcls/package/anaconda/envs/python3.7env/bin/activate
```

Custom packages are maintained in `/usr/local/lcls/model/python`:
```bash
export PYTHONPATH=$PYTHONPATH:/usr/local/lcls/model/python
```



### Lattice files

Lattice files are maintained in standard locations, and are referred to with these standard environmental variables:

```bash
export LCLS_LATTICE=/usr/local/lcls/model/lattice/lcls-lattice
export LCLS_CLASSIC_LATTICE=/usr/local/lcls/model/lattice/lcls-classic-lattice
```

These files are updated with `git`:

```bash
cd /usr/local/lcls/model/lattice/lcls-lattice
git pull -r
```
